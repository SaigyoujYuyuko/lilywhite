"""真实文件下载基准的 AyaFileIO、Aopen 与 Litestar File 对称应用。"""

from collections.abc import AsyncIterator
from pathlib import Path

import ayafileio
from litestar import Litestar, get
from litestar.response import File, Stream

from lilywhite import AyaFileIO
from lilywhite.http.result import stream


def create_aya_file_app(path: str, chunk_size: int) -> Litestar:
    """使用 LilyWhite FileIO 的 AyaFileIO 实现逐块返回文件。"""
    source = Path(path)
    file_io = AyaFileIO()
    headers = {"Content-Length": str(source.stat().st_size)}

    @get("/benchmark")
    async def download() -> Stream:
        return stream(
            file_io.stream(source, chunk_size=chunk_size),
            headers=headers,
            media_type="application/octet-stream",
        )

    return Litestar(route_handlers=[download], logging_config=None)


def create_aya_aopen_file_app(path: str, chunk_size: int) -> Litestar:
    """使用 aopen 并行打开句柄，再以相同定位读取逐块返回文件。"""
    source = Path(path)
    headers = {"Content-Length": str(source.stat().st_size)}

    async def content() -> AsyncIterator[bytes]:
        """保持与 FileIO.stream 相同的 read_at 分块语义。"""
        position = 0
        async with ayafileio.aopen(source, "rb") as file:
            while True:
                chunk = await file.read_at(position, chunk_size)
                if not chunk:
                    return
                yield chunk
                position += len(chunk)

    @get("/benchmark")
    async def download() -> Stream:
        return stream(content(), headers=headers, media_type="application/octet-stream")

    return Litestar(route_handlers=[download], logging_config=None)


def create_litestar_file_app(path: str, chunk_size: int) -> Litestar:
    """使用相同分块大小的 Litestar 原生 File 响应。"""
    source = Path(path)

    @get("/benchmark")
    async def download() -> File:
        return File(source, chunk_size=chunk_size, media_type="application/octet-stream")

    return Litestar(route_handlers=[download], logging_config=None)


__all__ = ["create_aya_aopen_file_app", "create_aya_file_app", "create_litestar_file_app"]
