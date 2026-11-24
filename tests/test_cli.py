"""LilyWhite 配置初始化命令的生成、加载与覆盖保护测试。"""

from pathlib import Path

import pytest

from lilywhite.__main__ import main
from lilywhite.cli.config import write_config
from lilywhite.config import ConfigLoader


def test_init_creates_loadable_config_and_protects_existing_file(tmp_path: Path) -> None:
    """默认模板应通过真实配置加载，已有文件不能被静默覆盖。"""
    destination = write_config(tmp_path / "nested" / "config.yaml")

    properties = ConfigLoader(destination).load()
    assert properties.version == 1
    assert properties.server.host == "127.0.0.1"
    assert properties.server.port == 8000
    assert properties.logging.level == "INFO"
    assert properties.operations.metrics_window_size == 4096

    original = destination.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError, match="--force"):
        write_config(destination)
    assert destination.read_text(encoding="utf-8") == original

    destination.write_text("version: 1\n", encoding="utf-8")
    write_config(destination, force=True)
    assert "server:" in destination.read_text(encoding="utf-8")


def test_main_init_command_reports_created_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """命令行入口应创建指定文件，并把结果写入 stderr。"""
    destination = tmp_path / "custom.yaml"

    main(["init", str(destination)])

    captured = capsys.readouterr()
    assert destination.exists()
    assert str(destination) in captured.err
    assert captured.out == ""
