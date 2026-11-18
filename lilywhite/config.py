"""通用服务配置模型与YAML加载。"""

from pathlib import Path
from urllib.parse import urlsplit

import msgspec
import yaml

CONFIG_VERSION = 1
_LOG_LEVELS = {"TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_LOG_COMPRESSIONS = {"zip", "gz", "bz2", "xz"}


class CorsProperties(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """允许跨域读取HTTP接口的来源，空元组表示关闭。"""

    allow_origins: tuple[str, ...] = ("null",)


class ServerProperties(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """HTTP监听和跨域配置。"""

    host: str = "127.0.0.1"
    port: int = 8000
    cors: CorsProperties = msgspec.field(default_factory=CorsProperties)


class LoggingProperties(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """日志输出、第三方过滤和文件轮转配置。"""

    level: str = "INFO"
    third_party_level: str = "WARNING"
    console: bool = True
    file: Path | None = None
    file_rotation_mb: int = 10
    file_retention_days: int = 14
    file_compression: str | None = "zip"


class OperationsProperties(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """运维日志订阅与请求指标配置。"""

    log_access_token: str | None = None
    metrics_window_size: int = 4096


class AppProperties(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """模板应用完整配置，业务配置可作为新分区扩展。"""

    version: int = CONFIG_VERSION
    server: ServerProperties = msgspec.field(default_factory=ServerProperties)
    logging: LoggingProperties = msgspec.field(default_factory=LoggingProperties)
    operations: OperationsProperties = msgspec.field(default_factory=OperationsProperties)


def _decode_value(target_type: type[object], value: object) -> object:
    """把YAML字符串解码为路径，其余类型交给msgspec。"""
    if target_type is Path and isinstance(value, str):
        return Path(value)
    raise TypeError(f"不支持的配置类型：{target_type}")


def _resolve_path(path: Path, base_dir: Path) -> Path:
    """以配置文件目录为基准解析相对路径。"""
    return path.resolve() if path.is_absolute() else (base_dir / path).resolve()


def _normalize_cors(properties: CorsProperties) -> CorsProperties:
    """校验并规范化跨域来源，保留null、通配符和HTTP(S)源。"""
    origins: list[str] = []
    for value in properties.allow_origins:
        origin = value.strip()
        if not origin or any(character.isspace() for character in origin):
            raise ValueError("server.cors.allow_origins 不能包含空来源或空白字符")
        if origin not in {"null", "*"}:
            try:
                parsed = urlsplit(origin)
            except ValueError as error:
                raise ValueError(f"server.cors.allow_origins 来源无效：{value}") from error
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
        if origin not in origins:
            origins.append(origin)
    return msgspec.structs.replace(properties, allow_origins=tuple(origins))


class ConfigLoader:
    """从明确路径加载、校验并规范化应用配置。"""

    def __init__(self, path: Path) -> None:
        """保存配置文件绝对路径，但不立即执行I/O。"""
        self._path = path.resolve()

    def load(self) -> AppProperties:
        """读取YAML，拒绝未知字段并返回规范化配置。"""
        raw: object = yaml.safe_load(self._path.read_text(encoding="utf-8"))
        properties = msgspec.convert(raw, AppProperties, dec_hook=_decode_value)
        if properties.version != CONFIG_VERSION:
            raise ValueError(f"不支持的配置版本：{properties.version}")
        if not 0 <= properties.server.port <= 65535:
            raise ValueError("server.port 必须在 0 到 65535 之间")
        if not 1 <= properties.operations.metrics_window_size <= 1_000_000:
            raise ValueError("operations.metrics_window_size 必须在 1 到 1000000 之间")
        if not 1 <= properties.logging.file_rotation_mb <= 10240:
            raise ValueError("logging.file_rotation_mb 必须在 1 到 10240 之间")
        if not 1 <= properties.logging.file_retention_days <= 3650:
            raise ValueError("logging.file_retention_days 必须在 1 到 3650 之间")
        compression = properties.logging.file_compression
        compression = compression.lower() if compression is not None else None
        if compression is not None and compression not in _LOG_COMPRESSIONS:
            raise ValueError("logging.file_compression 仅支持 zip、gz、bz2、xz 或 null")
        log_token = properties.operations.log_access_token
        if log_token is not None and (len(log_token) < 32 or not log_token.isascii()):
            raise ValueError("operations.log_access_token 必须至少包含 32 个 ASCII 字符")

        level = properties.logging.level.upper()
        if level not in _LOG_LEVELS:
            raise ValueError(f"logging.level 不受支持：{properties.logging.level}")
        third_party_level = properties.logging.third_party_level.upper()
        if third_party_level not in _LOG_LEVELS:
            raise ValueError(f"logging.third_party_level 不受支持：{properties.logging.third_party_level}")
        file = properties.logging.file
        server = msgspec.structs.replace(
            properties.server,
            cors=_normalize_cors(properties.server.cors),
        )
        logging = msgspec.structs.replace(
            properties.logging,
            level=level,
            third_party_level=third_party_level,
            file=None if file is None else _resolve_path(file, self._path.parent),
            file_compression=compression,
        )
        return msgspec.structs.replace(properties, server=server, logging=logging)


__all__ = [
    "CONFIG_VERSION",
    "AppProperties",
    "ConfigLoader",
    "CorsProperties",
    "LoggingProperties",
    "OperationsProperties",
    "ServerProperties",
]
