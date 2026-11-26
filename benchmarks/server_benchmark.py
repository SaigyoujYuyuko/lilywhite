"""使用独立 Uvicorn 服务进程和 HTTPX 客户端测量真实 TCP/HTTP 请求。"""

import argparse
import asyncio
import json
import multiprocessing
import platform
import socket
import statistics
from datetime import datetime
from pathlib import Path
from time import perf_counter

import httpx
import uvicorn

from .network_apps import create_lilywhite_app, create_native_app


def _free_port() -> int:
    """由操作系统分配当前空闲的本地端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _serve(implementation: str, port: int) -> None:
    """在独立进程中创建指定应用并启动同一个 Uvicorn 配置。"""
    factories = {"lilywhite": create_lilywhite_app, "native_litestar": create_native_app}
    app = factories[implementation]()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="critical",
        access_log=False,
    )
    uvicorn.Server(config).run()


async def _wait_ready(client: httpx.AsyncClient, process: multiprocessing.Process) -> None:
    """等待真实 HTTP 服务就绪，启动失败时立即报告子进程状态。"""
    for _ in range(100):
        if process.exitcode is not None:
            raise RuntimeError(f"Uvicorn 提前退出：{process.exitcode}")
        try:
            response = await client.get("/benchmark")
            if response.status_code == 200:
                return
        except httpx.ConnectError:
            pass
        await asyncio.sleep(0.05)
    raise TimeoutError("等待 Uvicorn 就绪超时")


async def _request(client: httpx.AsyncClient) -> float:
    """执行一次真实网络请求，校验业务响应并记录客户端延迟。"""
    started = perf_counter()
    response = await client.get("/benchmark")
    elapsed = perf_counter() - started
    response.raise_for_status()
    if response.json() != {"active": True}:
        raise AssertionError(f"网络基准响应错误：{response.text}")
    return elapsed


def _latency_metrics(samples: list[float]) -> dict[str, float]:
    """把网络请求延迟样本转换为毫秒分位数。"""
    ordered = sorted(samples)
    return {
        "mean_ms": statistics.fmean(ordered) * 1000,
        "p50_ms": ordered[int(len(ordered) * 0.50)] * 1000,
        "p95_ms": ordered[int(len(ordered) * 0.95)] * 1000,
        "p99_ms": ordered[int(len(ordered) * 0.99)] * 1000,
    }


async def _measure_server(
    implementation: str, port: int, requests: int, concurrency: int
) -> dict[str, object]:
    """启动一个服务进程，完成预热、顺序请求和限流并发请求。"""
    context = multiprocessing.get_context("spawn")
    process = context.Process(target=_serve, args=(implementation, port), name=f"{implementation}-{port}")
    process.start()
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    try:
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}",
            limits=limits,
            timeout=30,
            trust_env=False,
        ) as client:
            await _wait_ready(client, process)
            for _ in range(20):
                await _request(client)

            started = perf_counter()
            sequential_samples = [await _request(client) for _ in range(requests)]
            sequential_seconds = perf_counter() - started

            semaphore = asyncio.Semaphore(concurrency)

            async def limited_request() -> float:
                async with semaphore:
                    return await _request(client)

            started = perf_counter()
            concurrent_samples = await asyncio.gather(*(limited_request() for _ in range(requests)))
            concurrent_seconds = perf_counter() - started
    finally:
        if process.is_alive():
            process.terminate()
        await asyncio.to_thread(process.join, 15)
        process.close()

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
    }


async def run_benchmark(requests: int, concurrency: int, rounds: int) -> dict[str, object]:
    """交替两种实现的运行顺序，降低固定先后顺序造成的偏差。"""
    runs: dict[str, list[dict[str, object]]] = {"lilywhite": [], "native_litestar": []}
    implementations = ("lilywhite", "native_litestar")
    for round_index in range(rounds):
        order = implementations if round_index % 2 == 0 else tuple(reversed(implementations))
        for implementation in order:
            runs[implementation].append(
                await _measure_server(implementation, _free_port(), requests, concurrency)
            )
    return {
        "recorded_at": datetime.now().astimezone().isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "transport": "HTTP/1.1 over TCP; separate Uvicorn server and HTTPX client processes",
        "rounds": rounds,
        "runs": runs,
    }


def main() -> None:
    """解析基准参数并输出便于保存比较的 JSON。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(run_benchmark(args.requests, args.concurrency, args.rounds))
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
