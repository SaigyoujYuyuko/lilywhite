"""根据框架默认配置生成项目配置模板。"""

import argparse
import sys
from pathlib import Path

import yaml

from ..config import AppProperties


def default_config() -> dict[str, object]:
    """从当前框架默认配置生成 YAML 映射，不包含示例业务分组。"""
    properties = AppProperties()
    return {
        "version": properties.version,
        "server": {
            "host": properties.server.host,
            "port": properties.server.port,
            "cors": {"allow_origins": list(properties.server.cors.allow_origins)},
        },
        "logging": {
            "level": properties.logging.level,
            "third_party_level": properties.logging.third_party_level,
            "console": properties.logging.console,
            "file": None if properties.logging.file is None else str(properties.logging.file),
            "file_rotation_mb": properties.logging.file_rotation_mb,
            "file_retention_days": properties.logging.file_retention_days,
            "file_compression": properties.logging.file_compression,
        },
        "operations": {
            "metrics_window_size": properties.operations.metrics_window_size,
            "log_access_token": properties.operations.log_access_token,
        },
    }


def write_config(path: Path, *, force: bool = False) -> Path:
    """写入默认配置模板；只有显式 force 才允许覆盖现有文件。"""
    destination = path.resolve()
    if destination.exists() and not force:
        raise FileExistsError(f"配置文件已存在：{destination}；需要覆盖时请使用 --force")
    destination.parent.mkdir(parents=True, exist_ok=True)
    rendered = "# LilyWhite 项目配置。按业务需要修改，敏感值只写入本地配置。\n" + yaml.safe_dump(
        default_config(),
        allow_unicode=True,
        sort_keys=False,
    )
    destination.write_text(rendered, encoding="utf-8")
    return destination


def init_config(argv: list[str] | None = None) -> None:
    """处理 lilywhite init 命令并输出创建的文件路径。"""
    parser = argparse.ArgumentParser(prog="lilywhite init", description="生成 LilyWhite 默认配置文件")
    parser.add_argument("path", nargs="?", type=Path, default=Path("config.yaml"))
    parser.add_argument("--force", action="store_true", help="覆盖已存在的配置文件")
    args = parser.parse_args(argv)
    destination = write_config(args.path, force=args.force)
    print(f"LilyWhite config created: {destination}", file=sys.stderr, flush=True)


__all__ = ["default_config", "init_config", "write_config"]
