"""模块化启动与持续 ASGI 请求的规模化基准。"""

import argparse
import asyncio
import gc
import json
import platform
import statistics
import sys
import tempfile
import tracemalloc
from datetime import datetime
from pathlib import Path
from time import perf_counter

from litestar import Litestar, get
from litestar.di import NamedDependency
from litestar.middleware import DefineMiddleware
from litestar.testing import AsyncTestClient

from lilywhite.app.container import DependencyContainer
from lilywhite.app.discovery import import_decorated_modules, scan_decorated_modules
from lilywhite.app.scope import RequestScopeMiddleware
from lilywhite.config import AppProperties
from lilywhite.decorators.service import registered_services
from lilywhite.logger import setup_logging
from lilywhite.utils.registry import LifetimeType


class RequestResource:
    """统计持续请求创建、存活和释放的资源数。"""

    created = 0
    closed = 0
    active = 0

    def __init__(self) -> None:
        type(self).created += 1
        type(self).active += 1

    async def close(self) -> None:
        type(self).closed += 1
        type(self).active -= 1


class TransientOption:
    """每个请求都必须重新创建的轻量对象。"""


class BenchmarkService:
    """组合一个 Scoped 资源和一个 Transient 对象。"""

    def __init__(self, resource: RequestResource, option: TransientOption) -> None:
        self.resource = resource
        self.option = option


@get("/benchmark")
async def benchmark_route(benchmark_service: NamedDependency[BenchmarkService]) -> dict[str, bool]:
    """让出事件循环一次，使并发 ASGI 调用真正交错执行。"""
    await asyncio.sleep(0)
    return {"active": benchmark_service.resource.active > 0}


def measure_modules(module_count: int) -> dict[str, float | int]:
    """分别测量 AST 扫描、精确导入和业务 Singleton 预创建。"""
    with tempfile.TemporaryDirectory(prefix="lilywhite-scale-") as directory:
        root = Path(directory)
        package = "scale_business_modules"
        package_root = root / package
        package_root.mkdir()
        (package_root / "__init__.py").write_text('"""规模基准包。"""\n', encoding="utf-8")
        for index in range(module_count):
            (package_root / f"module_{index:04d}.py").write_text(
                f"from lilywhite import service\n@service\nclass Service{index:04d}:\n    pass\n",
                encoding="utf-8",
            )
        sys.path.insert(0, str(root))
        try:
            started = perf_counter()
            modules = scan_decorated_modules(package)
            scan_seconds = perf_counter() - started

            started = perf_counter()
            import_decorated_modules(package)
            import_seconds = perf_counter() - started

            container = DependencyContainer(package_names=(package,))
            for registration in registered_services((package,)):
                container.register_service(registration.service_type, registration.lifetime)
            started = perf_counter()
            container.build()
            singleton_seconds = perf_counter() - started
            assert len(modules) == module_count
            return {
                "modules": module_count,
                "ast_scan_seconds": scan_seconds,
                "module_import_seconds": import_seconds,
                "singleton_prebuild_seconds": singleton_seconds,
            }
        finally:
            sys.path.remove(str(root))


async def _asgi_request(app: Litestar) -> float:
    """直接执行一次真实 Litestar ASGI 调用并返回延迟。"""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/benchmark",
        "raw_path": b"/benchmark",
        "root_path": "",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
    }
    incoming = [{"type": "http.request", "body": b"", "more": False}]
    outgoing: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return incoming.pop(0) if incoming else {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        outgoing.append(message)

    started = perf_counter()
    await app(scope, receive, send)
    elapsed = perf_counter() - started
    assert outgoing[0]["status"] == 200
    return elapsed


def _request_app() -> Litestar:
    """创建使用真实 LilyWhite Scoped 中间件的 Litestar 应用。"""
    container = DependencyContainer()
    container.register_component(RequestResource, RequestResource, LifetimeType.SCOPED)
    container.register_component(TransientOption, TransientOption, LifetimeType.TRANSIENT)
    container.register_service(BenchmarkService, LifetimeType.SCOPED)
    container.build()
    return Litestar(
        route_handlers=[benchmark_route],
        dependencies=container.litestar_dependencies(),
        middleware=[DefineMiddleware(RequestScopeMiddleware, container=container)],
        logging_config=None,
    )


def _latency_metrics(samples: list[float]) -> dict[str, float]:
    """计算请求延迟分布，输入单位为秒，输出单位为毫秒。"""
    ordered = sorted(samples)
    return {
        "mean_ms": statistics.fmean(ordered) * 1000,
        "p50_ms": ordered[int(len(ordered) * 0.50)] * 1000,
        "p95_ms": ordered[int(len(ordered) * 0.95)] * 1000,
        "p99_ms": ordered[int(len(ordered) * 0.99)] * 1000,
    }


async def measure_requests(requests: int, concurrency: int) -> dict[str, object]:
    """测量顺序和并发 ASGI 请求，并检查持续运行后的内存与资源回收。"""
    app = _request_app()
    async with AsyncTestClient(app):
        for _ in range(20):
            await _asgi_request(app)
        RequestResource.created = RequestResource.closed = RequestResource.active = 0

        started = perf_counter()
        sequential = [_asgi_request(app) for _ in range(requests)]
        sequential_samples = [await call for call in sequential]
        sequential_seconds = perf_counter() - started

        semaphore = asyncio.Semaphore(concurrency)

        async def limited_request() -> float:
            async with semaphore:
                return await _asgi_request(app)

        started = perf_counter()
        concurrent_samples = await asyncio.gather(*(limited_request() for _ in range(requests)))
        concurrent_seconds = perf_counter() - started

        gc.collect()
        tracemalloc.start()
        before, _peak = tracemalloc.get_traced_memory()
        sustained = await asyncio.gather(*(limited_request() for _ in range(requests)))
        after, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert sustained
        assert RequestResource.active == 0
        assert RequestResource.created == RequestResource.closed == requests * 3

    return {
        "requests_per_scenario": requests,
        "concurrency": concurrency,
        "sequential": {
            "seconds": sequential_seconds,
            "requests_per_second": requests / sequential_seconds,
            **_latency_metrics(sequential_samples),
        },
        "concurrent": {
            "seconds": concurrent_seconds,
            "requests_per_second": requests / concurrent_seconds,
            **_latency_metrics(concurrent_samples),
        },
        "sustained": {
            "memory_before_bytes": before,
            "memory_after_bytes": after,
            "memory_delta_bytes": after - before,
            "memory_peak_bytes": peak,
            "resources_created": RequestResource.created,
            "resources_closed": RequestResource.closed,
            "resources_active": RequestResource.active,
        },
    }


def run_benchmark(module_count: int, requests: int, concurrency: int) -> dict[str, object]:
    """执行启动、请求和内存基准。"""
    settings = AppProperties().override(logging={"console": False}).logging
    setup_logging(settings, intercept_standard_logging=False)
    return {
        "recorded_at": datetime.now().astimezone().isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "startup": measure_modules(module_count),
        "requests": asyncio.run(measure_requests(requests, concurrency)),
    }


def main() -> None:
    """运行规模基准并保存 JSON。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--modules", type=int, default=100)
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_benchmark(args.modules, args.requests, args.concurrency)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
