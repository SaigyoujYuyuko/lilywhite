"""Loguru 日志配置与标准日志桥接。"""

import asyncio
import contextlib
import inspect
import logging as std_logging
import os
import sys
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, ClassVar

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


class LoggerManager:
    """管理进程级日志初始化和带模块标签的 Logger。"""

    _cache: ClassVar[dict[str, loguru.Logger]] = {}
    _initialized: ClassVar[bool] = False
    _initialization_lock: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def initialize(cls, settings: ConfigSection) -> None:
        """幂等初始化进程日志，重复调用不会替换现有配置。"""
        with cls._initialization_lock:
            if cls._initialized:
                return
            setup_logging(settings)
            cls._initialized = True

    @staticmethod
    def get_logger(module_name: str) -> loguru.Logger:
        """返回带固定模块标签的缓存 Logger。"""
        if module_name not in LoggerManager._cache:
            LoggerManager._cache[module_name] = logger.bind(module=module_name)
        return LoggerManager._cache[module_name]


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


__all__ = [
    "ConfigSection",
    "LoggerManager",
    "LoguruHandler",
    "logger",
    "setup_logging",
    "shutdown_logging",
    "third_party_log_filter",
]
