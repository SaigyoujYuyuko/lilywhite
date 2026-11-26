"""批量文件基准的 read_bytes_many、aopen 与普通 open 对照应用。"""

import asyncio

import ayafileio
from litestar import Litestar, get


def _result(contents: list[bytes] | tuple[bytes, ...]) -> dict[str, int]:
    """用读取结果构造响应，防止任何实现跳过真实文件内容。"""
    return {"files": len(contents), "bytes": sum(len(content) for content in contents)}


def create_many_app(paths: tuple[str, ...], max_concurrency: int) -> Litestar:
    """使用 AyaFileIO 原生批量读取入口。"""

    @get("/benchmark")
    async def batch() -> dict[str, int]:
        contents = await ayafileio.read_bytes_many(paths, max_concurrency=max_concurrency)
        return _result(contents)

    return Litestar(route_handlers=[batch], logging_config=None)


def create_gather_open_app(paths: tuple[str, ...], _max_concurrency: int) -> Litestar:
    """使用 gather 并发执行普通 open 合并读取路径。"""

    @get("/benchmark")
    async def batch() -> dict[str, int]:
        contents = await asyncio.gather(*(ayafileio.read_bytes(path) for path in paths))
        return _result(contents)

    return Litestar(route_handlers=[batch], logging_config=None)


def create_gather_aopen_app(paths: tuple[str, ...], _max_concurrency: int) -> Litestar:
    """使用 gather 并发执行 aopen，让操作系统打开操作进入原生线程池。"""

    async def read(path: str) -> bytes:
        """打开单个文件并读取全部内容。"""
        async with ayafileio.aopen(path, "rb") as file:
            return await file.read()

    @get("/benchmark")
    async def batch() -> dict[str, int]:
        contents = await asyncio.gather(*(read(path) for path in paths))
        return _result(contents)

    return Litestar(route_handlers=[batch], logging_config=None)


def create_serial_open_app(paths: tuple[str, ...], _max_concurrency: int) -> Litestar:
    """使用普通 open 合并读取路径逐个串行处理文件。"""

    @get("/benchmark")
    async def batch() -> dict[str, int]:
        contents = [await ayafileio.read_bytes(path) for path in paths]
        return _result(contents)

    return Litestar(route_handlers=[batch], logging_config=None)


__all__ = [
    "create_gather_aopen_app",
    "create_gather_open_app",
    "create_many_app",
    "create_serial_open_app",
]
