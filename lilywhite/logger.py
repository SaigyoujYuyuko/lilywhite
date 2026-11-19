"""Loguru 日志配置与标准日志桥接。"""

import asyncio
import contextlib
import inspect
import logging as std_logging
import os
import sys
import threading
from collections.abc import Callable
from types import TracebackType
from typing import TYPE_CHECKING, ClassVar, cast

import loguru
from loguru import logger

from .config import ConfigSection

if TYPE_CHECKING:
    from loguru import Record as LoguruRecord
else:
    LoguruRecord = dict[str, object]


_LOGURU_FULL_TRACEBACK = os.environ.get("LOGURU_FULL_TRACEBACK", "0").lower() in ("1", "true", "yes")
_SUPPRESSED_LOW_LEVEL_LOGGERS = {"httpcore", "httpx", "asyncio", "aiohttp"}
_SUPPRESSED_THIRD_PARTY_LOGGERS = {"nonebot", "uvicorn", "websockets"}
_handlers: dict[str, int | None] = {"console": None, "file": None}


def third_party_log_filter(minimum_level: str) -> Callable[[LoguruRecord], bool]:
    """按配置的最低级别过滤Uvicorn等第三方组件日志。"""
    minimum_number = logger.level(minimum_level).no

    def accept(record: LoguruRecord) -> bool:
        """允许应用日志及达到第三方最低级别的记录。"""
        name = (record["name"] or "").split(".")[0]
        if name in _SUPPRESSED_THIRD_PARTY_LOGGERS:
            return record["level"].no >= minimum_number
        return True

    return accept


class LoguruHandler(std_logging.Handler):
    """把标准 logging 记录转发到 Loguru。"""

    def emit(self, record: std_logging.LogRecord) -> None:
        """转换日志级别、调用位置和异常信息后写入 Loguru。"""
        if (
            record.name.split(".")[0] in _SUPPRESSED_LOW_LEVEL_LOGGERS
            and record.levelno < std_logging.WARNING
        ):
            return

        if record.name.split(".")[0] == "uvicorn":
            exc_type = record.exc_info[0] if record.exc_info else None
            if exc_type is not None and issubclass(exc_type, (KeyboardInterrupt, asyncio.CancelledError)):
                return
            message = record.getMessage()
            if message.startswith("Traceback") and (
                "KeyboardInterrupt" in message or "asyncio.exceptions.CancelledError" in message
            ):
                return

        level: str | int
        if record.levelno == std_logging.DEBUG:
            level = "TRACE"
        else:
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno

        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == std_logging.__file__):
            frame = frame.f_back
            depth += 1

        exc = record.exc_info if _LOGURU_FULL_TRACEBACK or record.levelno >= std_logging.ERROR else False
        logger.opt(depth=depth, exception=exc, colors=False).bind(
            module=record.name.split(".")[0].upper()
        ).log(level, "{}", record.getMessage())


type LogTarget = loguru.Logger | std_logging.Logger
type LoggerFactory = Callable[[str], LogTarget]
type ExceptionInfo = tuple[type[BaseException], BaseException | None, TracebackType | None]
type StandardExceptionInfo = tuple[type[BaseException], BaseException, TracebackType | None]


class ModuleLogger:
    """把固定的花括号日志风格适配到 Loguru 或标准 logging。"""

    def __init__(self, module_name: str, exception: ExceptionInfo | None = None) -> None:
        """保存模块标签和可选异常，实际 Logger 在写入时解析。"""
        self._module_name = module_name
        self._exception = exception

    def opt(self, *, exception: ExceptionInfo | None = None) -> ModuleLogger:
        """保留 Loguru opt(exception=...) 写法，并适配标准 logging。"""
        return ModuleLogger(self._module_name, exception)

    def trace(self, message: str, *args: object, **kwargs: object) -> None:
        """记录 TRACE；标准 logging 使用 DEBUG。"""
        self._write("trace", message, args, kwargs)

    def debug(self, message: str, *args: object, **kwargs: object) -> None:
        """记录 DEBUG。"""
        self._write("debug", message, args, kwargs)

    def info(self, message: str, *args: object, **kwargs: object) -> None:
        """记录 INFO。"""
        self._write("info", message, args, kwargs)

    def warning(self, message: str, *args: object, **kwargs: object) -> None:
        """记录 WARNING。"""
        self._write("warning", message, args, kwargs)

    def error(self, message: str, *args: object, **kwargs: object) -> None:
        """记录 ERROR。"""
        self._write("error", message, args, kwargs)

    def critical(self, message: str, *args: object, **kwargs: object) -> None:
        """记录 CRITICAL。"""
        self._write("critical", message, args, kwargs)

    def exception(self, message: str, *args: object, **kwargs: object) -> None:
        """记录当前异常。"""
        self._write("exception", message, args, kwargs)

    def _write(
        self,
        level: str,
        message: str,
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> None:
        """完成花括号插值，并显式调用目标级别的日志方法。"""
        target = LoggerManager._get_target(self._module_name)
        rendered = message.format(*args, **kwargs) if args or kwargs else message
        if isinstance(target, std_logging.Logger):
            exc_info = cast(StandardExceptionInfo | None, self._exception)
            match level:
                case "trace" | "debug":
                    target.debug(rendered, exc_info=exc_info, stacklevel=3)
                case "info":
                    target.info(rendered, exc_info=exc_info, stacklevel=3)
                case "warning":
                    target.warning(rendered, exc_info=exc_info, stacklevel=3)
                case "error":
                    target.error(rendered, exc_info=exc_info, stacklevel=3)
                case "critical":
                    target.critical(rendered, exc_info=exc_info, stacklevel=3)
                case _:
                    target.exception(rendered, exc_info=exc_info, stacklevel=3)
            return

        configured = target.opt(depth=2, exception=self._exception)
        match level:
            case "trace":
                configured.trace(rendered)
            case "debug":
                configured.debug(rendered)
            case "info":
                configured.info(rendered)
            case "warning":
                configured.warning(rendered)
            case "error":
                configured.error(rendered)
            case "critical":
                configured.critical(rendered)
            case _:
                configured.exception(rendered)


def _validate_log_target(target: object) -> None:
    """拒绝无法明确适配的日志对象。"""
    if not isinstance(target, (type(logger), std_logging.Logger)):
        raise TypeError("自定义 Logger 必须是 logging.Logger、loguru.Logger 或对应工厂")


class LoggerManager:
    """管理进程级日志初始化、自定义 Logger 和模块标签。"""

    _cache: ClassVar[dict[str, LogTarget]] = {}
    _logger_factory: ClassVar[LoggerFactory | None] = None
    _initialized: ClassVar[bool] = False
    _initialization_lock: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def initialize(cls, settings: ConfigSection) -> None:
        """幂等初始化进程日志，自定义 Logger 由其调用方负责配置。"""
        with cls._initialization_lock:
            if cls._initialized:
                return
            if cls._logger_factory is None:
                setup_logging(settings)
            cls._initialized = True

    @classmethod
    def _get_target(cls, module_name: str) -> LogTarget:
        """取得当前模块的 Loguru Logger 或自定义 Logger。"""
        if module_name not in cls._cache:
            target: LogTarget
            if cls._logger_factory is None:
                target = logger.bind(module=module_name)
            else:
                target = cls._logger_factory(module_name)
                _validate_log_target(target)
            cls._cache[module_name] = target
        return cls._cache[module_name]

    @staticmethod
    def get_logger(module_name: str) -> ModuleLogger:
        """返回保持模块标签且能响应后续 Logger 替换的适配器。"""
        return ModuleLogger(module_name)


def setup_logging(settings: ConfigSection, intercept_standard_logging: bool = True) -> None:
    """配置控制台、文件输出和标准 logging 桥接。"""
    json_logs = os.environ.get("THLW_LOG_JSON", "0").lower() in {"1", "true", "yes"}
    for handler_id in _handlers.values():
        if handler_id is not None:
            with contextlib.suppress(ValueError):
                logger.remove(handler_id)
    with contextlib.suppress(ValueError):
        logger.remove(0)
    logger.configure(extra={"module": "APP", "request_id": ""})
    _handlers["console"] = None
    _handlers["file"] = None

    log_format_file = (
        "[{time:YYYY-MM-DDTHH:mm:ss.SSSZ}] {level.name:<8} "
        "| pid={process.id} thread={thread.name} "
        "| {name} [{extra[module]}] "
        "| {extra[request_id]} {message}"
    )
    log_format_console = (
        "<level>[{time:HH:mm:ss.SSS}] {level.name:<8} "
        "| {name} | [{extra[module]}] {extra[request_id]} {message}</level>"
    )
    third_party_filter = third_party_log_filter(settings.third_party_level)

    if settings.console:
        _handlers["console"] = logger.add(
            sys.stderr,
            format=log_format_console,
            level=settings.level.upper(),
            colorize=not json_logs,
            serialize=json_logs,
            backtrace=False,
            diagnose=False,
            enqueue=True,
            filter=third_party_filter,
        )
    if settings.file is not None:
        settings.file.parent.mkdir(parents=True, exist_ok=True)
        _handlers["file"] = logger.add(
            str(settings.file),
            format=log_format_file,
            level=settings.level.upper(),
            rotation=f"{settings.file_rotation_mb} MB",
            serialize=json_logs,
            compression=settings.file_compression,
            retention=f"{settings.file_retention_days} days",
            backtrace=False,
            diagnose=False,
            enqueue=True,
            filter=third_party_filter,
        )

    if intercept_standard_logging:
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi"):
            named_logger = std_logging.getLogger(name)
            named_logger.handlers.clear()
            named_logger.propagate = True
        root_logger = std_logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        root_logger.addHandler(LoguruHandler())
        root_logger.setLevel(std_logging.DEBUG)


def shutdown_logging() -> None:
    """移除日志输出并等待异步日志队列处理完毕。"""
    for name, handler_id in _handlers.items():
        if handler_id is not None:
            with contextlib.suppress(ValueError):
                logger.remove(handler_id)
        _handlers[name] = None
    logger.complete()
    LoggerManager._initialized = False


def override_logger(custom_logger: LogTarget | LoggerFactory | None) -> None:
    """替换进程内 LilyWhite Logger；传 None 恢复 Loguru。"""
    factory: LoggerFactory | None
    if custom_logger is None:
        factory = None
    elif isinstance(custom_logger, (type(logger), std_logging.Logger)):
        instance = custom_logger

        def use_instance(_module_name: str) -> LogTarget:
            return instance

        factory = use_instance
    else:
        logger_factory = cast(LoggerFactory, custom_logger)
        _validate_log_target(logger_factory("APP"))
        factory = logger_factory

    shutdown_logging()
    with LoggerManager._initialization_lock:
        LoggerManager._logger_factory = factory
        LoggerManager._cache.clear()


__all__ = [
    "ConfigSection",
    "LogTarget",
    "LoggerFactory",
    "LoggerManager",
    "LoguruHandler",
    "ModuleLogger",
    "logger",
    "override_logger",
    "setup_logging",
    "shutdown_logging",
    "third_party_log_filter",
]
