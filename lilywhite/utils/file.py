"""可替换的异步文件组件，默认使用 AyaFileIO 原生后端。"""

from collections.abc import AsyncIterable, AsyncIterator
from os import PathLike
from typing import Protocol

import ayafileio

from .component import component

type FilePath = str | PathLike[str]
type FileContent = bytes | bytearray | memoryview

_DEFAULT_STREAM_CHUNK_SIZE = 64 * 1024


class FileIO(Protocol):
    """面向业务的异步文件读写接口；路径和访问控制由调用方负责。"""

    async def read_bytes(self, path: FilePath, *, offset: int = 0, size: int = -1) -> bytes:
        """读取整个文件，或从 offset 开始读取至多 size 字节；负数表示读到末尾。"""
        ...

    async def write_bytes(self, path: FilePath, data: FileContent) -> int:
        """覆盖写入全部字节并处理短写，返回写入字节数。"""
        ...

    async def read_text(self, path: FilePath, *, encoding: str = "utf-8") -> str:
        """按指定编码读取整个文本文件。"""
        ...

    async def write_text(self, path: FilePath, text: str, *, encoding: str = "utf-8") -> int:
        """覆盖写入全部文本并处理短写，返回写入字符数。"""
        ...

    def stream(
        self,
        path: FilePath,
        *,
        offset: int = 0,
        size: int = -1,
        chunk_size: int = _DEFAULT_STREAM_CHUNK_SIZE,
    ) -> AsyncIterator[bytes]:
        """逐块读取文件范围，每块都是调用方可以安全持有的独立 bytes。"""
        ...

    async def write_stream(self, path: FilePath, chunks: AsyncIterable[FileContent]) -> int:
        """覆盖写入异步字节流并处理短写，返回总字节数。"""
        ...

    async def copy(self, source: FilePath, destination: FilePath) -> int:
        """复制整个文件，优先使用操作系统提供的快速路径。"""
        ...


async def _write_bytes(file: ayafileio.AsyncFile[bytes], data: FileContent) -> int:
    """在当前文件位置完整写入一个二进制缓冲区。"""
    view = memoryview(data)
    written = 0
    while written < len(view):
        count = await file.write(view[written:])
        if count <= 0:
            raise OSError("文件写入没有取得进展")
        written += count
    return written


async def _write_text(file: ayafileio.AsyncFile[str], text: str) -> int:
    """按 AyaFileIO 的字符计数约定完整写入文本。"""
    written = 0
    while written < len(text):
        count = await file.write(text[written:])
        if count <= 0:
            raise OSError("文件写入没有取得进展")
        written += count
    return written


@component(interface=FileIO, fallback=True)
class AyaFileIO:
    """无状态的 FileIO 适配器；每次操作独立打开并关闭文件句柄。"""

    async def read_bytes(self, path: FilePath, *, offset: int = 0, size: int = -1) -> bytes:
        """整文件读取走原生合并路径，范围读取使用定位 I/O。"""
        if offset < 0:
            raise ValueError("offset 不能为负数")
        if offset == 0 and size < 0:
            return await ayafileio.read_bytes(path)
        async with ayafileio.open(path, "rb") as file:
            return await file.read_at(offset, size)

    async def write_bytes(self, path: FilePath, data: FileContent) -> int:
        """覆盖写入完整的内存缓冲区。"""
        async with ayafileio.open(path, "wb") as file:
            return await _write_bytes(file, data)

    async def read_text(self, path: FilePath, *, encoding: str = "utf-8") -> str:
        """读取文本，默认明确使用 UTF-8 而非平台区域编码。"""
        return await ayafileio.read_text(path, encoding=encoding)

    async def write_text(self, path: FilePath, text: str, *, encoding: str = "utf-8") -> int:
        """覆盖写入文本，返回字符数而不是编码后的字节数。"""
        async with ayafileio.open(path, "w", encoding=encoding) as file:
            return await _write_text(file, text)

    async def stream(
        self,
        path: FilePath,
        *,
        offset: int = 0,
        size: int = -1,
        chunk_size: int = _DEFAULT_STREAM_CHUNK_SIZE,
    ) -> AsyncIterator[bytes]:
        """使用定位读取生成独立字节块，调用方无需管理复用缓冲区。"""
        if offset < 0:
            raise ValueError("offset 不能为负数")
        if chunk_size <= 0:
            raise ValueError("chunk_size 必须为正数")
        async with ayafileio.open(path, "rb") as file:
            position = offset
            remaining = size
            while remaining != 0:
                read_size = chunk_size if remaining < 0 else min(chunk_size, remaining)
                chunk = await file.read_at(position, read_size)
                if not chunk:
                    return
                yield chunk
                position += len(chunk)
                if remaining > 0:
                    remaining -= len(chunk)

    async def write_stream(self, path: FilePath, chunks: AsyncIterable[FileContent]) -> int:
        """逐块消费异步输入，避免把整个上传文件装入内存。"""
        written = 0
        async with ayafileio.open(path, "wb") as file:
            async for chunk in chunks:
                written += await _write_bytes(file, chunk)
        return written

    async def copy(self, source: FilePath, destination: FilePath) -> int:
        """复制文件，系统快速路径不可用时由 AyaFileIO 自动回退。"""
        return await ayafileio.acopy(source, destination)


__all__ = ["AyaFileIO", "FileContent", "FileIO", "FilePath"]
