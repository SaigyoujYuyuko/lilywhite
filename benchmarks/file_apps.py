"""真实文件下载基准的 AyaFileIO 与 Litestar File 对称应用。"""

from pathlib import Path

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


def create_litestar_file_app(path: str, chunk_size: int) -> Litestar:
    """使用相同分块大小的 Litestar 原生 File 响应。"""
    source = Path(path)

    @get("/benchmark")
    async def download() -> File:
        return File(source, chunk_size=chunk_size, media_type="application/octet-stream")

    return Litestar(route_handlers=[download], logging_config=None)


__all__ = ["create_aya_file_app", "create_litestar_file_app"]
