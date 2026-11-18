"""LilyWhite 标志性入口装饰器、ASGI 适配与统一启动函数。"""

import argparse
from pathlib import Path

import msgspec
import uvicorn
from litestar import Litestar
from litestar.types import Receive, Scope, Send

from ..config import AppProperties, ConfigLoader
from ..logger import shutdown_logging
from .application import LilyWhiteApplication


def _business_package(main_type: type[object]) -> str:
    """从入口类所在模块推导顶层业务包。"""
    package = main_type.__module__.partition(".")[0]
    if not package:
        raise TypeError("无法从入口类确定业务包")
    return package


def _create_application(
    main_type: type[object], properties: AppProperties, backends: str | tuple[str, ...]
) -> Litestar:
    """按入口类约定装配框架运维模块和业务模块。"""
    package = _business_package(main_type)
    return LilyWhiteApplication(
        properties,
        backends=backends,
        controller_packages=("lilywhite.controller", f"{package}.controller"),
        service_package=f"{package}.services",
        storage_package=f"{package}.storage",
    ).create_app()


def LilywhiteMain[T](target: type[T]) -> type[T]:
    """标记入口类并注入标准 ASGI 调用接口，不生成代理类型。"""
    setattr(target, "__lilywhite_main__", True)  # noqa: B010

    async def asgi_call(self: object, scope: Scope, receive: Receive, send: Send) -> None:
        """缓存当前入口实例的 Litestar 应用并转发 ASGI 调用。"""
        application = getattr(self, "__lilywhite_asgi_application__", None)
        if not isinstance(application, Litestar):
            properties = ConfigLoader(Path("config.yaml")).load()
            application = _create_application(type(self), properties, "memory")
            setattr(self, "__lilywhite_asgi_application__", application)  # noqa: B010
        await application(scope, receive, send)

    setattr(target, "__call__", asgi_call)  # noqa: B010
    return target


def run(main_type: type[object], argv: list[str] | None = None) -> None:
    """从已标记入口类推导业务包，组合框架并启动 Uvicorn。"""
    if getattr(main_type, "__lilywhite_main__", False) is not True:
        raise TypeError("启动入口类必须使用 @LilywhiteMain 标记")

    parser = argparse.ArgumentParser(description="LilyWhite Framework application")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--backend", action="append", help="启用后端，可重复传入")
    parser.add_argument(
        "--log-level",
        type=str.upper,
        choices=("TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
    )
    parser.add_argument("--log-file", type=Path)
    parser.add_argument("--no-console", action="store_true")
    args = parser.parse_args(argv)

    properties = ConfigLoader(args.config).load()
    server = msgspec.structs.replace(
        properties.server,
        host=properties.server.host if args.host is None else args.host,
        port=properties.server.port if args.port is None else args.port,
    )
    logging = msgspec.structs.replace(
        properties.logging,
        level=properties.logging.level if args.log_level is None else args.log_level,
        console=properties.logging.console and not args.no_console,
        file=properties.logging.file if args.log_file is None else args.log_file.resolve(),
    )
    properties = msgspec.structs.replace(properties, server=server, logging=logging)

    completed_normally = False
    try:
        backends = tuple(args.backend or ["memory"])
        application = _create_application(main_type, properties, backends)
        uvicorn.run(
            application,
            host=properties.server.host,
            port=properties.server.port,
            log_config={"version": 1, "disable_existing_loggers": False},
        )
        completed_normally = True
    finally:
        if completed_normally:
            shutdown_logging()


__all__ = ["LilywhiteMain", "run"]
