"""声明式配置分组、装饰器校验与 YAML 加载。"""

from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from types import UnionType
from typing import Any, get_args, get_origin
from urllib.parse import urlsplit

import yaml

CONFIG_VERSION = 1
_LOG_LEVELS = {"TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_LOG_COMPRESSIONS = {"zip", "gz", "bz2", "xz"}
Converter = Callable[[Any, Path | None], Any]
Validator = Callable[[Any], bool]


def _matches_type(value: object, expected: object) -> bool:
    """支持普通类型、Union 和固定/变长 tuple 的运行时检查。"""
    if expected is Any:
        return True
    origin = get_origin(expected)
    if origin in (UnionType, __import__("typing").Union):
        return any(_matches_type(value, item) for item in get_args(expected))
    if origin is tuple:
        if not isinstance(value, tuple):
            return False
        arguments = get_args(expected)
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            return all(_matches_type(item, arguments[0]) for item in value)
        return len(value) == len(arguments) and all(
            _matches_type(item, item_type) for item, item_type in zip(value, arguments, strict=True)
        )
    return isinstance(expected, type) and isinstance(value, expected)


class ConfigSetting:
    """保存一个配置值的默认值、类型和可选转换器。"""

    def __init__(self, default: Any, value_type: object, converter: Converter | None) -> None:
        self.default = default
        self.value_type = type(default) if value_type is None else value_type
        self.converter = converter
        self.value = default

    def convert(self, value: Any, base_dir: Path | None) -> Any:
        """转换 YAML 值并保留默认类型约束。"""
        converted = self.converter(value, base_dir) if self.converter is not None else value
        if not _matches_type(converted, self.value_type):
            raise TypeError(f"配置值类型不匹配：期望 {self.value_type}，实际 {type(converted)}")
        return converted


class ConfigSection:
    """提供 section.value 读取方式的轻量配置分组。"""

    def __init__(self, **values: Any) -> None:
        self._settings: dict[str, ConfigSetting] = {}
        for name, value in values.items():
            if isinstance(value, ConfigSection):
                setattr(self, name, value)
            else:
                self._settings[name] = (
                    value if isinstance(value, ConfigSetting) else ConfigSetting(value, type(value), None)
                )

    def __getattr__(self, name: str) -> Any:
        """读取分组值，未知名称直接报错。"""
        settings = self.__dict__.get("_settings", {})
        if name in settings:
            return settings[name].value
        raise AttributeError(f"未知配置项：{name}")

    def _update(self, values: Mapping[str, Any], base_dir: Path | None) -> None:
        """递归更新已知配置值，不静默接受拼错的字段。"""
        for name, value in values.items():
            current = self._settings.get(name)
            if current is not None:
                current.value = current.convert(value, base_dir)
            elif name in self.__dict__ and isinstance(self.__dict__[name], ConfigSection):
                if not isinstance(value, Mapping):
                    raise TypeError(f"配置分组 {name} 必须使用映射")
                self.__dict__[name]._update(value, base_dir)
            else:
                raise ValueError(f"未知配置项：{name}")


def setting(
    default: Any, *, value_type: object | None = None, converter: Converter | None = None
) -> ConfigSetting:
    """声明需要显式类型或转换器的配置值。"""
    return ConfigSetting(default, value_type if value_type is not None else type(default), converter)


def section(**values: Any) -> ConfigSection:
    """声明一个配置分组，无需为分组创建专用类。"""
    return ConfigSection(**values)


def validate[T](path: str, predicate: Validator) -> Callable[[T], T]:
    """把路径和 lambda 条件注册为配置类校验器。"""

    def decorate(target: T) -> T:
        validators = list(getattr(target, "__config_validators__", ()))
        validators.append((path, predicate))
        setattr(target, "__config_validators__", validators)  # noqa: B010
        return target

    return decorate


class Config:
    """通过分组和装饰器校验构成一份完整应用配置。"""

    def __init__(self) -> None:
        for name, value in vars(type(self)).items():
            if name.startswith("_") or callable(value):
                continue
            setattr(self, name, deepcopy(value))
        self._validate()

    def _apply(self, changes: Mapping[str, Any], base_dir: Path | None = None) -> None:
        """按 YAML 映射覆盖默认值并保留未知字段检查。"""
        for name, value in changes.items():
            current = getattr(self, name, None)
            if isinstance(current, ConfigSection):
                if not isinstance(value, Mapping):
                    raise TypeError(f"配置分组 {name} 必须使用映射")
                current._update(value, base_dir)
            elif name in vars(type(self)):
                expected = type(current)
                if not _matches_type(value, expected):
                    raise TypeError(f"配置项 {name} 类型不匹配")
                setattr(self, name, value)
            else:
                raise ValueError(f"未知配置项：{name}")
        self._validate()

    def override[T: Config](self: T, **changes: Any) -> T:
        """返回应用覆盖值后的配置副本，原配置保持不变。"""
        cloned = deepcopy(self)
        cloned._apply(changes)
        return cloned

    def _validate(self) -> None:
        """执行类上按声明顺序注册的全部校验器。"""
        for path, predicate in getattr(type(self), "__config_validators__", ()):
            value: Any = self
            for part in path.split("."):
                value = getattr(value, part)
            if not predicate(value):
                raise ValueError(f"配置项 {path} 校验失败")


def _path_value(value: Any, base_dir: Path | None) -> Path | None:
    """把日志路径转换为相对配置文件目录的绝对路径。"""
    if value is None:
        return None
    path = Path(value)
    return path.resolve() if path.is_absolute() or base_dir is None else (base_dir / path).resolve()


def _tuple_value(value: Any, _base_dir: Path | None) -> tuple[Any, ...]:
    """把 YAML 列表转换为不可变元组。"""
    return tuple(value)


def _normalize_origins(origins: tuple[str, ...]) -> tuple[str, ...]:
    """去除 CORS 来源的空白、末尾斜杠和重复项。"""
    normalized: list[str] = []
    for value in origins:
        origin = value.strip()
        if not origin or any(character.isspace() for character in origin):
            raise ValueError("server.cors.allow_origins 不能包含空来源或空白字符")
        if origin not in {"null", "*"}:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(f"server.cors.allow_origins 来源无效：{value}")
            origin = origin.rstrip("/")
        if origin not in normalized:
            normalized.append(origin)
    return tuple(normalized)


@validate("version", lambda value: value == CONFIG_VERSION)
@validate("server.port", lambda value: 0 <= value <= 65535)
@validate("operations.metrics_window_size", lambda value: 1 <= value <= 1_000_000)
@validate("logging.file_rotation_mb", lambda value: 1 <= value <= 10240)
@validate("logging.file_retention_days", lambda value: 1 <= value <= 3650)
@validate("logging.level", lambda value: value.upper() in _LOG_LEVELS)
@validate("logging.third_party_level", lambda value: value.upper() in _LOG_LEVELS)
@validate("logging.file_compression", lambda value: value is None or value.lower() in _LOG_COMPRESSIONS)
@validate(
    "operations.log_access_token",
    lambda value: value is None or (len(value) >= 32 and value.isascii()),
)
class AppProperties(Config):
    """应用默认配置，新增业务分组只需添加 section。"""

    version = CONFIG_VERSION
    server = section(
        host="127.0.0.1",
        port=8000,
        cors=section(
            allow_origins=setting(("null",), value_type=tuple[str, ...], converter=_tuple_value),
        ),
    )
    logging = section(
        level="INFO",
        third_party_level="WARNING",
        console=True,
        file=setting(None, value_type=Path | None, converter=_path_value),
        file_rotation_mb=10,
        file_retention_days=14,
        file_compression=setting("zip", value_type=str | None),
    )
    operations = section(
        log_access_token=setting(None, value_type=str | None),
        metrics_window_size=4096,
    )


class ConfigLoader:
    """从明确路径读取 YAML，并返回校验和规范化后的配置。"""

    def __init__(self, path: Path) -> None:
        self._path = path.resolve()

    def load(self) -> AppProperties:
        """加载默认配置、YAML 覆盖和规范化值。"""
        raw: object = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, Mapping):
            raise TypeError("配置文件顶层必须是映射")
        properties = AppProperties()
        properties._apply(raw, self._path.parent)
        return properties.override(
            server={"cors": {"allow_origins": _normalize_origins(properties.server.cors.allow_origins)}},
            logging={
                "level": properties.logging.level.upper(),
                "third_party_level": properties.logging.third_party_level.upper(),
                "file_compression": (
                    properties.logging.file_compression.lower()
                    if properties.logging.file_compression is not None
                    else None
                ),
            },
        )


__all__ = [
    "CONFIG_VERSION",
    "AppProperties",
    "Config",
    "ConfigLoader",
    "ConfigSection",
    "section",
    "setting",
    "validate",
]
