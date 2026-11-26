"""通过真实 HTTP 请求对比 AyaFileIO 批量读取、并发打开与串行读取。"""

import argparse
import asyncio
import json
import multiprocessing
import os
import platform
import tempfile
from datetime import datetime
from pathlib import Path
from time import perf_counter

import httpx
import uvicorn

from .batch_apps import (
    create_gather_aopen_app,
    create_gather_open_app,
    create_many_app,
    create_serial_open_app,
)
from .file_benchmark import _free_port, _latency_metrics, _throughput_metrics


def _serve(implementation: str, paths: tuple[str, ...], max_concurrency: int, port: int) -> None:
    """在独立进程中启动指定批量读取应用。"""
    factories = {
        "ayafileio_many": create_many_app,
        "ayafileio_gather_open": create_gather_open_app,
        "ayafileio_gather_aopen": create_gather_aopen_app,
        "ayafileio_serial_open": create_serial_open_app,
    }
    app = factories[implementation](paths, max_concurrency)
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="critical",
        access_log=False,
    )
    uvicorn.Server(config).run()


async def _request(client: httpx.AsyncClient, file_count: int, total_bytes: int) -> float:
    """校验全部文件均已读取，并记录请求延迟。"""
    started = perf_counter()
    response = await client.get("/benchmark")
    elapsed = perf_counter() - started
    response.raise_for_status()
    if response.json() != {"files": file_count, "bytes": total_bytes}:
        raise AssertionError(f"批量读取响应错误：{response.text}")
    return elapsed


async def _wait_ready(
    client: httpx.AsyncClient,
    process: multiprocessing.Process,
    file_count: int,
    total_bytes: int,
) -> None:
    """通过真实批量请求等待服务就绪。"""
    for _ in range(100):
        if process.exitcode is not None:
            raise RuntimeError(f"Uvicorn 提前退出：{process.exitcode}")
        try:
            await _request(client, file_count, total_bytes)
        except httpx.ConnectError:
            pass
        else:
            return
        await asyncio.sleep(0.05)
    raise TimeoutError("等待批量文件服务器就绪超时")


async def _measure_server(
    implementation: str,
    paths: tuple[str, ...],
    total_bytes: int,
    requests: int,
    concurrency: int,
    max_open_concurrency: int,
) -> dict[str, object]:
    """测量单个批量实现的顺序与并发请求。"""
    port = _free_port()
    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=_serve,
        args=(implementation, paths, max_open_concurrency, port),
        name=f"{implementation}-batch-{port}",
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
            await _wait_ready(client, process, len(paths), total_bytes)
            for _ in range(2):
                await _request(client, len(paths), total_bytes)

            started = perf_counter()
            sequential_samples = [await _request(client, len(paths), total_bytes) for _ in range(requests)]
            sequential_seconds = perf_counter() - started

            semaphore = asyncio.Semaphore(concurrency)

            async def limited_request() -> float:
                async with semaphore:
                    return await _request(client, len(paths), total_bytes)

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
            **_throughput_metrics(sequential_seconds, requests, total_bytes),
            **_latency_metrics(sequential_samples),
        },
        "concurrent": {
            **_throughput_metrics(concurrent_seconds, requests, total_bytes),
            **_latency_metrics(concurrent_samples),
        },
    }


async def run_benchmark(
    file_count: int,
    file_size: int,
    requests: int,
    concurrency: int,
    rounds: int,
    max_open_concurrency: int,
) -> dict[str, object]:
    """创建一组独立文件并交替测量四种批量读取方式。"""
    implementations = (
        "ayafileio_many",
        "ayafileio_gather_open",
        "ayafileio_gather_aopen",
        "ayafileio_serial_open",
    )
    with tempfile.TemporaryDirectory(prefix="lilywhite-batch-") as directory:
        root = Path(directory)
        paths: list[str] = []
        for index in range(file_count):
            path = root / f"payload-{index:04d}.bin"
            path.write_bytes(os.urandom(file_size))
            paths.append(str(path))
        total_bytes = file_count * file_size
        runs: dict[str, list[dict[str, object]]] = {implementation: [] for implementation in implementations}
        for round_index in range(rounds):
            order = implementations if round_index % 2 == 0 else tuple(reversed(implementations))
            for implementation in order:
                runs[implementation].append(
                    await _measure_server(
                        implementation,
                        tuple(paths),
                        total_bytes,
                        requests,
                        concurrency,
                        max_open_concurrency,
                    )
                )
    return {
        "recorded_at": datetime.now().astimezone().isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "transport": "HTTP/1.1 over TCP; separate Uvicorn and HTTPX processes",
        "throughput_note": "MiB/s counts file bytes read, not the small JSON response body",
        "file_count": file_count,
        "file_size_bytes": file_size,
        "total_bytes_per_request": total_bytes,
        "max_open_concurrency": max_open_concurrency,
        "rounds": rounds,
        "runs": runs,
    }


def main() -> None:
    """运行批量文件网络基准并保存 JSON。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", type=int, default=32)
    parser.add_argument("--file-size", type=int, default=65536)
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--max-open-concurrency", type=int, default=64)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(
        run_benchmark(
            args.files,
            args.file_size,
            args.requests,
            args.concurrency,
            args.rounds,
            args.max_open_concurrency,
        )
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
