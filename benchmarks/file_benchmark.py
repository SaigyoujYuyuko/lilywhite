"""使用独立进程测量 AyaFileIO 与 Litestar File 的真实网络文件下载。"""

import argparse
import asyncio
import json
import multiprocessing
import os
import platform
import socket
import statistics
import tempfile
from datetime import datetime
from pathlib import Path
from time import perf_counter

import httpx
import uvicorn

from .file_apps import create_aya_aopen_file_app, create_aya_file_app, create_litestar_file_app


def _free_port() -> int:
    """由操作系统分配空闲回环端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _serve(implementation: str, path: str, chunk_size: int, port: int) -> None:
    """在独立进程中启动相同 Uvicorn 配置的文件下载服务。"""
    factories = {
        "ayafileio": create_aya_file_app,
        "ayafileio_aopen": create_aya_aopen_file_app,
        "litestar_file": create_litestar_file_app,
    }
    app = factories[implementation](path, chunk_size)
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="critical",
        access_log=False,
    )
    uvicorn.Server(config).run()


def _latency_metrics(samples: list[float]) -> dict[str, float]:
    """计算文件完整下载延迟的毫秒分位数。"""
    ordered = sorted(samples)
    return {
        "mean_ms": statistics.fmean(ordered) * 1000,
        "p50_ms": ordered[int(len(ordered) * 0.50)] * 1000,
        "p95_ms": ordered[int(len(ordered) * 0.95)] * 1000,
        "p99_ms": ordered[int(len(ordered) * 0.99)] * 1000,
    }


def _throughput_metrics(seconds: float, requests: int, file_size: int) -> dict[str, float]:
    """同时计算请求吞吐和实际文件载荷吞吐。"""
    mib = file_size * requests / (1024 * 1024)
    return {
        "seconds": seconds,
        "requests_per_second": requests / seconds,
        "mib_per_second": mib / seconds,
    }


async def _wait_ready(client: httpx.AsyncClient, process: multiprocessing.Process, file_size: int) -> None:
    """通过一次完整文件下载确认服务已经就绪。"""
    for _ in range(100):
        if process.exitcode is not None:
            raise RuntimeError(f"Uvicorn 提前退出：{process.exitcode}")
        try:
            await _request(client, file_size)
        except httpx.ConnectError:
            pass
        else:
            return
        await asyncio.sleep(0.05)
    raise TimeoutError("等待文件服务器就绪超时")


async def _request(client: httpx.AsyncClient, file_size: int) -> float:
    """流式消费完整响应，校验载荷大小且不把整个文件保存在内存。"""
    started = perf_counter()
    received = 0
    async with client.stream("GET", "/benchmark") as response:
        response.raise_for_status()
        async for chunk in response.aiter_bytes():
            received += len(chunk)
    elapsed = perf_counter() - started
    if received != file_size:
        raise AssertionError(f"文件下载大小不匹配：期望 {file_size}，实际 {received}")
    return elapsed


async def _measure_server(
    implementation: str,
    path: str,
    file_size: int,
    chunk_size: int,
    requests: int,
    concurrency: int,
) -> dict[str, object]:
    """对单个文件尺寸和执行实现完成预热、顺序与并发下载。"""
    port = _free_port()
    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=_serve,
        args=(implementation, path, chunk_size, port),
        name=f"{implementation}-file-{port}",
    )
    process.start()
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    try:
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}",
            limits=limits,
            timeout=120,
            trust_env=False,
        ) as client:
            await _wait_ready(client, process, file_size)
            for _ in range(2):
                await _request(client, file_size)

            started = perf_counter()
            sequential_samples = [await _request(client, file_size) for _ in range(requests)]
            sequential_seconds = perf_counter() - started

            semaphore = asyncio.Semaphore(concurrency)

            async def limited_request() -> float:
                async with semaphore:
                    return await _request(client, file_size)

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
            **_throughput_metrics(sequential_seconds, requests, file_size),
            **_latency_metrics(sequential_samples),
        },
        "concurrent": {
            **_throughput_metrics(concurrent_seconds, requests, file_size),
            **_latency_metrics(concurrent_samples),
        },
    }


async def run_benchmark(
    sizes: tuple[int, ...],
    requests: int,
    concurrency: int,
    rounds: int,
    chunk_size: int,
) -> dict[str, object]:
    """逐文件尺寸交替三种实现，输出全部独立运行结果。"""
    scenarios: list[dict[str, object]] = []
    implementations = ("ayafileio", "ayafileio_aopen", "litestar_file")
    for file_size in sizes:
        with tempfile.TemporaryDirectory(prefix="lilywhite-file-") as directory:
            path = Path(directory) / "payload.bin"
            path.write_bytes(os.urandom(file_size))
            runs: dict[str, list[dict[str, object]]] = {
                "ayafileio": [],
                "ayafileio_aopen": [],
                "litestar_file": [],
            }
            for round_index in range(rounds):
                order = implementations if round_index % 2 == 0 else tuple(reversed(implementations))
                for implementation in order:
                    runs[implementation].append(
                        await _measure_server(
                            implementation,
                            str(path),
                            file_size,
                            chunk_size,
                            requests,
                            concurrency,
                        )
                    )
            scenarios.append({"file_size_bytes": file_size, "runs": runs})
    return {
        "recorded_at": datetime.now().astimezone().isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "transport": "HTTP/1.1 over TCP; streaming client; separate Uvicorn and HTTPX processes",
        "chunk_size_bytes": chunk_size,
        "rounds": rounds,
        "scenarios": scenarios,
    }


def _sizes(value: str) -> tuple[int, ...]:
    """解析逗号分隔的字节尺寸，拒绝空值和非正数。"""
    sizes = tuple(int(item.strip()) for item in value.split(","))
    if not sizes or any(size <= 0 for size in sizes):
        raise ValueError("文件尺寸必须是正整数")
    return sizes


def main() -> None:
    """运行真实文件网络基准并保存 JSON。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", type=_sizes, default=(65536, 1048576, 8388608))
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--chunk-size", type=int, default=65536)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(
        run_benchmark(args.sizes, args.requests, args.concurrency, args.rounds, args.chunk_size)
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
