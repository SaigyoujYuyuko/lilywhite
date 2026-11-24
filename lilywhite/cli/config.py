"""根据框架和业务默认配置生成项目配置模板。"""

import argparse
import sys
from importlib import import_module
from pathlib import Path

import yaml

from ..config import AppProperties, ConfigSection, SecretRef


def _yaml_value(value: object) -> object:
    """把配置默认值转换为 YAML 可表示的标量、列表或映射。"""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, SecretRef):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple | list):
        return [_yaml_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _yaml_value(item) for key, item in value.items()}
    return value


def _section_values(section: ConfigSection) -> dict[str, object]:
    """递归读取配置声明，保留环境变量引用而不解析本机密钥。"""
    values: dict[str, object] = {}
    for name, setting in section._settings.items():
        values[name] = _yaml_value(setting.default)
    for name, value in section.__dict__.items():
        if isinstance(value, ConfigSection):
            values[name] = _section_values(value)
    return values


def default_config(properties_type: type[AppProperties] = AppProperties) -> dict[str, object]:
    """直接读取类型声明，避免生成模板时实例化配置或读取密钥。"""
    values: dict[str, object] = {}
    for base in reversed(properties_type.__mro__):
        for name, value in vars(base).items():
            if name.startswith("_") or callable(value):
                continue
            values[name] = _section_values(value) if isinstance(value, ConfigSection) else _yaml_value(value)
    return values


def _entry_properties_type(reference: str) -> type[AppProperties]:
    """按 module:Class 导入业务入口并读取 properties_type。"""
    module_name, separator, class_name = reference.partition(":")
    if not separator or not module_name or not class_name:
        raise ValueError("--entry 必须使用 my_app.application:MyApplication 格式")
    module = import_module(module_name)
    try:
        entry_type = module.__dict__[class_name]
    except KeyError as error:
        raise TypeError(f"入口类不存在：{reference}") from error
    if not isinstance(entry_type, type):
        raise TypeError(f"入口目标不是类：{reference}")
    try:
        properties_type = entry_type.properties_type  # type: ignore[attr-defined]
    except AttributeError:
        return AppProperties
    if not isinstance(properties_type, type) or not issubclass(properties_type, AppProperties):
        raise TypeError(f"入口 properties_type 必须是 AppProperties 子类：{reference}")
    return properties_type


def write_config(
    path: Path,
    *,
    force: bool = False,
    properties_type: type[AppProperties] = AppProperties,
) -> Path:
    """写入默认配置模板；只有显式 force 才允许覆盖现有文件。"""
    destination = path.resolve()
    if destination.exists() and not force:
        raise FileExistsError(f"配置文件已存在：{destination}；需要覆盖时请使用 --force")
    destination.parent.mkdir(parents=True, exist_ok=True)
    rendered = "# LilyWhite 项目配置。按业务需要修改，敏感值只写入本地配置。\n" + yaml.safe_dump(
        default_config(properties_type),
        allow_unicode=True,
        sort_keys=False,
    )
    destination.write_text(rendered, encoding="utf-8")
    return destination


def init_config(argv: list[str] | None = None) -> None:
    """处理 lilywhite init 命令并输出创建的文件路径。"""
    parser = argparse.ArgumentParser(prog="lilywhite init", description="生成 LilyWhite 默认配置文件")
    parser.add_argument("path", nargs="?", type=Path, default=Path("config.yaml"))
    parser.add_argument("--entry", help="业务入口，格式为 my_app.application:MyApplication")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的配置文件")
    args = parser.parse_args(argv)
    properties_type = AppProperties if args.entry is None else _entry_properties_type(args.entry)
    destination = write_config(args.path, force=args.force, properties_type=properties_type)
    print(f"LilyWhite config created: {destination}", file=sys.stderr, flush=True)


__all__ = ["default_config", "init_config", "write_config"]
