"""声明式配置分组、装饰器校验与 YAML 加载。"""

import os
import re
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import UnionType
from typing import Any, ClassVar, cast, get_args, get_origin, overload
from urllib.parse import urlsplit

import yaml
from msgspec import Meta

CONFIG_VERSION = 1
Converter = Callable[[Any, Path | None], Any]
Validator = Callable[[Any], bool]
_ENV_REFERENCE = re.compile(r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass(frozen=True)
class SecretRef:
    """只保存环境变量名，字符串形式始终可安全写入模板和日志。"""

    name: str
    required: bool = True

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.name):
            raise ValueError(f"环境变量名无效：{self.name}")

    def __str__(self) -> str:
        return f"${{{self.name}}}"


def env(name: str, *, required: bool = True) -> SecretRef:
    """声明一个环境变量引用；required=False 时未设置返回 None。"""
    return SecretRef(name, required)


def _resolve_secret(value: Any) -> Any:
    """解析 SecretRef 或 ${ENV_NAME}，错误信息只包含变量名。"""
    if isinstance(value, SecretRef):
        reference = value
    elif isinstance(value, str) and (match := _ENV_REFERENCE.fullmatch(value)) is not None:
        reference = SecretRef(match.group("name"))
    else:
        return value
    if reference.name in os.environ:
        return os.environ[reference.name]
    if reference.required:
        raise ValueError(f"环境变量 {reference.name} 未设置")
    return None


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


def _validate_meta(value: Any, meta: Meta | None) -> None:
    """执行 Meta 中的数值、正则和长度约束。"""
    if meta is None or value is None:
        return
    if meta.gt is not None and not value > meta.gt:
        raise ValueError(f"配置值必须大于 {meta.gt}")
    if meta.ge is not None and not value >= meta.ge:
        raise ValueError(f"配置值必须大于或等于 {meta.ge}")
    if meta.lt is not None and not value < meta.lt:
        raise ValueError(f"配置值必须小于 {meta.lt}")
    if meta.le is not None and not value <= meta.le:
        raise ValueError(f"配置值必须小于或等于 {meta.le}")
    if meta.multiple_of is not None:
        if meta.multiple_of == 0:
            raise ValueError("multiple_of 不能为 0")
        if value % meta.multiple_of != 0:
            raise ValueError(f"配置值必须是 {meta.multiple_of} 的倍数")
    if meta.min_length is not None and len(value) < meta.min_length:
        raise ValueError(f"配置值长度不能小于 {meta.min_length}")
    if meta.max_length is not None and len(value) > meta.max_length:
        raise ValueError(f"配置值长度不能大于 {meta.max_length}")
    if meta.pattern is not None and re.search(meta.pattern, value) is None:
        raise ValueError(f"配置值必须匹配正则 {meta.pattern}")


class ConfigSetting:
    """保存一个配置值的默认值、类型、Meta 约束和可选转换器。"""

    def __init__(
        self, default: Any, value_type: object, converter: Converter | None, meta: Meta | None = None
    ) -> None:
        self.default = default
        self.value_type: object
        if value_type is None:
            self.value_type = (
                (str if default.required else str | None) if isinstance(default, SecretRef) else type(default)
            )
        else:
            self.value_type = value_type
        self.converter = converter
        self.meta = meta
        self.value = default
        if not isinstance(default, SecretRef):
            _validate_meta(default, meta)

    def resolve_default(self) -> None:
        """在配置对象实例化时解析默认环境引用，而不是模块导入时。"""
        self.value = _resolve_secret(self.default)
        _validate_meta(self.value, self.meta)

    def __deepcopy__(self, memo: dict[int, Any]) -> ConfigSetting:
        """复制配置值，共享不可变的 Meta 约束和转换函数。"""
        cloned = ConfigSetting(deepcopy(self.default, memo), self.value_type, self.converter, self.meta)
        cloned.value = deepcopy(self.value, memo)
        memo[id(self)] = cloned
        return cloned

    def convert(self, value: Any, base_dir: Path | None) -> Any:
        """转换 YAML 值和环境引用，再执行类型与 Meta 约束。"""
        converted = self.converter(value, base_dir) if self.converter is not None else value
        converted = _resolve_secret(converted)
        if not _matches_type(converted, self.value_type):
            raise TypeError(f"配置值类型不匹配：期望 {self.value_type}，实际 {type(converted)}")
        _validate_meta(converted, self.meta)
        return converted


class ConfigSection:
    """提供 section.value 读取方式的轻量配置分组。"""

    def __init__(self, **values: Any) -> None:
        self._settings: dict[str, ConfigSetting] = {}
        for name, value in values.items():
            if isinstance(value, ConfigSection):
                self.__dict__[name] = value
            else:
                self._settings[name] = (
                    value if isinstance(value, ConfigSetting) else ConfigSetting(value, type(value), None)
                )

    def _resolve_secrets(self) -> None:
        """递归解析当前配置对象中的环境变量引用。"""
        for setting_value in self._settings.values():
            setting_value.resolve_default()
        for value in self.__dict__.values():
            if isinstance(value, ConfigSection):
                value._resolve_secrets()

    def _read(self, name: str) -> Any:
        """从值设置或嵌套分组中读取一个字段。"""
        settings = self.__dict__.get("_settings", {})
        if name in settings:
            return settings[name].value
        nested = self.__dict__.get(name)
        if isinstance(nested, ConfigSection):
            return nested
        raise AttributeError(f"未知配置项：{name}")

    def __getattr__(self, name: str) -> Any:
        """把未找到的实例属性转交给配置字段表。"""
        return self._read(name)

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
    default: Any,
    *,
    value_type: object | None = None,
    converter: Converter | None = None,
    meta: Meta | None = None,
) -> ConfigSetting:
    """声明需要显式类型、转换器或 Meta 约束的配置值。"""
    return ConfigSetting(default, value_type, converter, meta)


def section(**values: Any) -> ConfigSection:
    """声明一个配置分组，无需为分组创建专用类。"""
    return ConfigSection(**values)


def validate[T](path: str, predicate: Validator) -> Callable[[T], T]:
    """把路径和 lambda 条件注册为配置类校验器。"""

    def decorate(target: T) -> T:
        config_type = cast(type[Config], target)
        validators = list(config_type.__config_validators__)
        validators.append((path, predicate))
        config_type.__config_validators__ = validators
        return target

    return decorate


class Config:
    """通过分组和装饰器校验构成一份完整应用配置。"""

    __config_validators__: ClassVar[list[tuple[str, Validator]]] = []

    def __init__(self) -> None:
        # 从基类到子类复制声明，让 AppProperties 子类保留框架配置分组。
        for base in reversed(type(self).__mro__):
            for name, value in vars(base).items():
                if name.startswith("_") or callable(value):
                    continue
                self.__dict__[name] = deepcopy(value)
        for value in self.__dict__.values():
            if isinstance(value, ConfigSection):
                value._resolve_secrets()
        self._validate()

    def _apply(self, changes: Mapping[str, Any], base_dir: Path | None = None) -> None:
        """按 YAML 映射覆盖默认值并保留未知字段检查。"""
        for name, value in changes.items():
            current = self.__dict__.get(name)
            if isinstance(current, ConfigSection):
                if not isinstance(value, Mapping):
                    raise TypeError(f"配置分组 {name} 必须使用映射")
                current._update(value, base_dir)
            elif name in self.__dict__:
                expected = type(current)
                if not _matches_type(value, expected):
                    raise TypeError(f"配置项 {name} 类型不匹配")
                self.__dict__[name] = value
            else:
                raise ValueError(f"未知配置项：{name}")
        self._validate()

    def override[T: Config](self: T, **changes: Any) -> T:
        """返回应用覆盖值后的配置副本，原配置保持不变。"""
        cloned = deepcopy(self)
        cloned._apply(changes)
        return cloned

    def _read_path(self, path: str) -> Any:
        """按点分路径读取嵌套配置值。"""
        value: Any = self
        for part in path.split("."):
            if isinstance(value, Config):
                value = value.__dict__[part]
            elif isinstance(value, ConfigSection):
                value = value._read(part)
            else:
                raise ValueError(f"配置路径无效：{path}")
        return value

    def _validate(self) -> None:
        """执行类上按声明顺序注册的全部校验器。"""
        for path, predicate in type(self).__config_validators__:
            if not predicate(self._read_path(path)):
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
@validate(
    "operations.log_access_token",
    lambda value: value is None or (len(value) >= 32 and value.isascii()),
)
class AppProperties(Config):
    """应用默认配置，新增业务分组只需添加 section。"""

    version = CONFIG_VERSION
    server = section(
        host="127.0.0.1",
        port=setting(8000, meta=Meta(ge=0, le=65535)),
        cors=section(
            allow_origins=setting(("null",), value_type=tuple[str, ...], converter=_tuple_value),
        ),
    )
    logging = section(
        level=setting("INFO", meta=Meta(pattern=r"(?i)^(?:TRACE|DEBUG|INFO|WARNING|ERROR|CRITICAL)$")),
        third_party_level=setting(
            "WARNING", meta=Meta(pattern=r"(?i)^(?:TRACE|DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
        ),
        console=True,
        file=setting(None, value_type=Path | None, converter=_path_value),
        file_rotation_mb=setting(10, meta=Meta(ge=1, le=10240)),
        file_retention_days=setting(14, meta=Meta(ge=1, le=3650)),
        file_compression=setting("zip", value_type=str | None, meta=Meta(pattern=r"(?i)^(?:zip|gz|bz2|xz)$")),
    )
    operations = section(
        log_access_token=setting(None, value_type=str | None),
        metrics_window_size=setting(4096, meta=Meta(ge=1, le=1_000_000)),
    )


class ConfigLoader:
    """从明确路径读取 YAML，并返回校验和规范化后的配置。"""

    def __init__(self, path: Path) -> None:
        self._path = path.resolve()

    @overload
    def load(self) -> AppProperties: ...

    @overload
    def load[T: AppProperties](self, properties_type: type[T]) -> T: ...

    def load(self, properties_type: type[AppProperties] | None = None) -> AppProperties:
        """按指定配置类型加载 YAML；省略时使用 AppProperties。"""
        raw: object = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, Mapping):
            raise TypeError("配置文件顶层必须是映射")
        target_type = AppProperties if properties_type is None else properties_type
        properties = target_type()
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
    "SecretRef",
    "env",
    "section",
    "setting",
    "validate",
]
