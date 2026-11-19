"""LilyWhite 标志性入口装饰器、ASGI 适配与统一启动函数。"""

import argparse
from pathlib import Path

import uvicorn
from litestar import Litestar
from litestar.types import Receive, Scope, Send

from ..banner import print_banner
from ..config import AppProperties, ConfigLoader
from ..logger import shutdown_logging
from .application import LilyWhiteApplication


def _business_package(main_type: type[object]) -> str:
    """从入口类所在模块推导顶层业务包。"""
    package = main_type.__module__.partition(".")[0]
    if not package:
        raise TypeError("无法从入口类确定业务包")
    return package


def _print_entry_banner(
    main_type: type[object],
    properties: AppProperties,
    external_server: bool = False,
    entry: object | None = None,
) -> None:
    """优先打印入口类自定义 Banner，否则使用默认样式和可选附加消息。"""
    custom_banner = getattr(entry, "banner", None)
    if custom_banner is not None:
        if not callable(custom_banner):
            raise TypeError("入口类 banner 必须是可调用方法")
        content = custom_banner()
        if not isinstance(content, str):
            raise TypeError("入口类 banner() 必须返回字符串")
        print(content)
        return
    print_banner(
        str(getattr(main_type, "application_name", "LilyWhite Application")),
        str(getattr(main_type, "application_version", "0.1.0")),
        None if external_server else properties.server.host,
        None if external_server else properties.server.port,
    )
    banner_message = getattr(entry, "banner_message", None)
    if banner_message is None:
        return
    if not callable(banner_message):
        raise TypeError("入口类 banner_message 必须是可调用方法")
    message = banner_message()
    if not isinstance(message, str):
        raise TypeError("入口类 banner_message() 必须返回字符串")
    print(message)


def _create_application(
    main_type: type[object],
    properties: AppProperties,
    backends: str | tuple[str, ...],
    entry: object | None = None,
    external_server: bool = False,
) -> Litestar:
    """装配框架和业务，并接入入口类声明的生命周期钩子。"""
    if getattr(main_type, "__lilywhite_main__", False) is not True:
        raise TypeError("启动入口类必须使用 @LilywhiteMain 标记")
    package = _business_package(main_type)
    framework = LilyWhiteApplication(
        properties,
        backends=backends,
        controller_packages=("lilywhite.controller",),
        business_package=package,
        application_name=str(getattr(main_type, "application_name", "LilyWhite Application")),
        external_server=external_server,
    )
    entry = main_type() if entry is None else entry
    for hook_name in ("on_startup", "on_shutdown"):
        hook = getattr(entry, hook_name, None)
        if hook is None:
            continue
        if not callable(hook):
            raise TypeError(f"入口类 {hook_name} 必须是可调用方法")
        if hook_name == "on_startup":
            framework.lifespan.register("entry_on_startup", "START")(hook)
        else:
            framework.lifespan.register("entry_on_shutdown", "STOP")(hook)
    return framework.create_app()


def LilywhiteMain[T](target: type[T]) -> type[T]:
    """标记入口类并注入标准 ASGI 调用接口，不生成代理类型。"""
    setattr(target, "__lilywhite_main__", True)  # noqa: B010

    async def asgi_call(self: object, scope: Scope, receive: Receive, send: Send) -> None:
        """缓存当前入口实例的 Litestar 应用并转发 ASGI 调用。"""
        application = getattr(self, "__lilywhite_asgi_application__", None)
        if not isinstance(application, Litestar):
            properties = ConfigLoader(Path("config.yaml")).load()
            _print_entry_banner(type(self), properties, external_server=True, entry=self)
            backends = getattr(self, "backends", ("memory",))
            application = _create_application(
                type(self), properties, backends, entry=self, external_server=True
            )
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
    properties = properties.override(
        server={
            "host": properties.server.host if args.host is None else args.host,
            "port": properties.server.port if args.port is None else args.port,
        },
        logging={
            "level": properties.logging.level if args.log_level is None else args.log_level,
            "console": properties.logging.console and not args.no_console,
            "file": properties.logging.file if args.log_file is None else args.log_file.resolve(),
        },
    )

    completed_normally = False
    try:
        default_backends = getattr(main_type, "backends", ("memory",))
        backends = tuple(args.backend) if args.backend else default_backends
        entry = main_type()
        _print_entry_banner(main_type, properties, entry=entry)
        application = _create_application(main_type, properties, backends, entry=entry)
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
