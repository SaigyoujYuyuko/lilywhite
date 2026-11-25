"""测量构造器元数据读取和依赖解析，供缓存前后直接对比。"""

import argparse
import asyncio
import json
import platform
import statistics
from datetime import datetime
from inspect import signature
from pathlib import Path
from time import perf_counter
from typing import get_type_hints

from lilywhite.app.DI.container import DependencyContainer
from lilywhite.config import AppProperties
from lilywhite.logger import setup_logging
from lilywhite.utils.registry import LifetimeType


class Leaf:
    """无下游依赖的 Transient 叶节点。"""


class Middle:
    """增加一层真实构造器读取。"""

    def __init__(self, leaf: Leaf) -> None:
        self.leaf = leaf


class Root:
    """基准解析入口。"""

    def __init__(self, middle: Middle) -> None:
        self.middle = middle


def measure_metadata(calls: int) -> dict[str, float | int]:
    """分别测量 inspect.signature 和 get_type_hints 的固定调用开销。"""
    started = perf_counter()
    for _ in range(calls):
        signature(Root.__init__)
    signature_seconds = perf_counter() - started

    started = perf_counter()
    for _ in range(calls):
        get_type_hints(Root.__init__, include_extras=True)
    hints_seconds = perf_counter() - started
    return {
        "calls": calls,
        "signature_seconds": signature_seconds,
        "get_type_hints_seconds": hints_seconds,
        "signature_calls_per_second": calls / signature_seconds,
        "get_type_hints_calls_per_second": calls / hints_seconds,
    }


async def measure_resolution(calls: int) -> dict[str, float | int]:
    """每次解析都创建三层 Transient，避免命中 Singleton 或 Scoped 缓存。"""
    container = DependencyContainer()
    container.register_service(Leaf, LifetimeType.TRANSIENT)
    container.register_service(Middle, LifetimeType.TRANSIENT)
    container.register_service(Root, LifetimeType.TRANSIENT)
    container.build()
    scope = container.create_scope()

    for _ in range(100):
        await scope.resolve(Root)
    samples: list[float] = []
    started = perf_counter()
    for _ in range(calls):
        call_started = perf_counter()
        await scope.resolve(Root)
        samples.append(perf_counter() - call_started)
    elapsed = perf_counter() - started
    samples.sort()
    return {
        "calls": calls,
        "seconds": elapsed,
        "resolutions_per_second": calls / elapsed,
        "mean_ms": statistics.fmean(samples) * 1000,
        "p50_ms": samples[int(len(samples) * 0.50)] * 1000,
        "p95_ms": samples[int(len(samples) * 0.95)] * 1000,
        "p99_ms": samples[int(len(samples) * 0.99)] * 1000,
    }


async def run_benchmark(calls: int) -> dict[str, object]:
    """执行一次完整 DI 基准并返回可保存的数据。"""
    settings = AppProperties().override(logging={"console": False}).logging
    setup_logging(settings, intercept_standard_logging=False)
    return {
        "recorded_at": datetime.now().astimezone().isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "metadata": measure_metadata(calls),
        "resolution": await measure_resolution(calls),
    }


def main() -> None:
    """运行基准并打印 JSON，可选保存到本地文件。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--calls", type=int, default=3000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(run_benchmark(args.calls))
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
