"""内置文件组件、真实文件操作和业务替换行为测试。"""

import asyncio
from collections.abc import AsyncIterator, Mapping
from pathlib import Path

import pytest

from lilywhite import AyaFileIO, FileIO
from lilywhite.app.container import DependencyContainer
from lilywhite.app.runtime import ApplicationRuntime
from lilywhite.config import AppProperties


def create_container(
    *,
    business_package: str | None = None,
    resources: Mapping[type[object], object] | None = None,
) -> DependencyContainer:
    """通过完整运行时补齐框架资源，再返回待验证的容器。"""
    return ApplicationRuntime(
        AppProperties(),
        business_package=business_package,
        resources=resources,
    ).container


def test_default_file_component_is_available() -> None:
    """没有业务文件组件时，容器提供内置 AyaFileIO。"""
    container = create_container()

    assert type(container.resolve(FileIO)) is AyaFileIO


def test_aya_file_component_performs_real_file_operations(tmp_path: Path) -> None:
    """通过容器提供的公开接口验证范围读取、流式读写、文本和复制。"""
    file_io = create_container().resolve(FileIO)
    payload = bytes(range(256)) * 1024

    async def exercise() -> None:
        source = tmp_path / "source.bin"
        streamed = tmp_path / "streamed.bin"
        copied = tmp_path / "copied.bin"
        text_path = tmp_path / "greeting.txt"

        assert await file_io.write_bytes(source, memoryview(payload)) == len(payload)
        assert await file_io.read_bytes(source, offset=257, size=4096) == payload[257:4353]

        chunks = [chunk async for chunk in file_io.stream(source, offset=128, size=5000, chunk_size=1024)]
        assert b"".join(chunks) == payload[128:5128]
        assert all(type(chunk) is bytes for chunk in chunks)

        async def input_chunks() -> AsyncIterator[memoryview]:
            view = memoryview(payload)
            for offset in range(0, len(view), 16384):
                yield view[offset : offset + 16384]

        assert await file_io.write_stream(streamed, input_chunks()) == len(payload)
        assert await file_io.read_bytes(streamed) == payload

        assert await file_io.copy(source, copied) == len(payload)
        assert await file_io.read_bytes(copied) == payload

        text = "春が来た！\nLilyWhite"
        assert await file_io.write_text(text_path, text) == len(text)
        assert await file_io.read_text(text_path) == text

    asyncio.run(exercise())


def _install_business_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    package: str,
    source: str,
) -> None:
    """创建一个由真实 AST 扫描发现的临时业务包。"""
    root = tmp_path / package
    root.mkdir()
    (root / "__init__.py").write_text('"""临时文件组件业务包。"""\n', encoding="utf-8")
    (root / "files.py").write_text(source, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))


def test_business_component_replaces_default_file_component(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """业务组件先绑定后，默认 FileIO 不应再覆盖它。"""
    package = "custom_file_component_app"
    _install_business_package(
        tmp_path,
        monkeypatch,
        package,
        "from lilywhite import AyaFileIO, FileIO, component\n"
        "@component(interface=FileIO)\n"
        "class BusinessFileIO(AyaFileIO):\n"
        "    pass\n",
    )

    container = create_container(business_package=package)

    assert type(container.resolve(FileIO)).__name__ == "BusinessFileIO"


def test_bean_replaces_default_file_component(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """返回 FileIO 的业务 Bean 同样优先于内置后备组件。"""
    package = "custom_file_bean_app"
    _install_business_package(
        tmp_path,
        monkeypatch,
        package,
        "from lilywhite import AyaFileIO, FileIO, bean, configuration\n"
        "class BusinessFileIO(AyaFileIO):\n"
        "    pass\n"
        "@configuration\n"
        "class FileConfiguration:\n"
        "    @bean\n"
        "    def file_io(self) -> FileIO:\n"
        "        return BusinessFileIO()\n",
    )

    container = create_container(business_package=package)

    assert type(container.resolve(FileIO)).__name__ == "BusinessFileIO"


def test_existing_file_instance_replaces_default_file_component() -> None:
    """显式传入的运行时实例保持最高优先级。"""
    file_io = AyaFileIO()

    container = create_container(resources={FileIO: file_io})

    assert container.resolve(FileIO) is file_io
