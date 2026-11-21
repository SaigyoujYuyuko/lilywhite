"""LilyWhite 标志性入口装饰器、ASGI 适配与统一启动函数。"""

import argparse
from pathlib import Path

import uvicorn
from litestar import Litestar
from litestar.types import Receive, Scope, Send

from ..banner import print_banner
from ..config import AppProperties, ConfigLoader
from ..logger import override_logger as use_custom_logger
from ..logger import shutdown_logging
from ..utils.registry import ManagedRegistry, ManagedRegistrySelection
from .application import LilyWhiteApplication


def _business_package(main_type: type[object]) -> str:
    """从入口类所在模块推导顶层业务包。"""
    package = main_type.__module__.partition(".")[0]
    if not package:
        raise TypeError("无法从入口类确定业务包")
    return package


def _is_main_type(main_type: type[object]) -> bool:
    """读取装饰器直接写在入口类上的标记。"""
    try:
        return main_type.__lilywhite_main__ is True  # type: ignore[attr-defined]
    except AttributeError:
        return False


def _application_name(main_type: type[object]) -> str:
    """读取入口类名称，未声明时使用框架默认值。"""
    try:
        return str(main_type.application_name)  # type: ignore[attr-defined]
    except AttributeError:
        return "LilyWhite Application"


def _application_version(main_type: type[object]) -> str:
    """读取入口类版本，未声明时使用初始版本。"""
    try:
        return str(main_type.application_version)  # type: ignore[attr-defined]
    except AttributeError:
        return "0.1.0"


def _properties_type(main_type: type[object]) -> type[AppProperties]:
    """读取入口声明的配置类型，未声明时使用框架默认配置。"""
    try:
        value = main_type.properties_type  # type: ignore[attr-defined]
    except AttributeError:
        return AppProperties
    if isinstance(value, type) and issubclass(value, AppProperties):
        return value
    raise TypeError("入口类 properties_type 必须是 AppProperties 子类")


def _managed_registries(entry: object) -> ManagedRegistrySelection:
    """读取入口显式声明的托管注册表，未声明时不扩大扫描范围。"""
    try:
        value = entry.managed_registries  # type: ignore[attr-defined]
    except AttributeError:
        return ()
    if not isinstance(value, tuple) or not all(isinstance(item, ManagedRegistry) for item in value):
        raise TypeError("入口类 managed_registries 必须是 ManagedRegistry 元组")
    return value


def _optional_imports(entry: object, properties: AppProperties) -> tuple[str, ...]:
    """读取当前配置下允许缺失依赖的禁用模块前缀。"""
    try:
        value = entry.optional_imports  # type: ignore[attr-defined]
    except AttributeError:
        return ()
    if callable(value):
        value = value(properties)
    if not isinstance(value, tuple) or not all(isinstance(item, str) and item for item in value):
        raise TypeError("入口类 optional_imports 必须返回非空模块前缀字符串元组")
    return value


def _print_entry_banner(
    main_type: type[object],
    properties: AppProperties,
    external_server: bool = False,
    entry: object | None = None,
) -> None:
    """优先打印入口类自定义 Banner，否则使用默认样式和可选附加消息。"""
    try:
        custom_banner = entry.banner  # type: ignore[union-attr]
    except AttributeError:
        custom_banner = None
    if custom_banner is not None:
        if not callable(custom_banner):
            raise TypeError("入口类 banner 必须是可调用方法")
        content = custom_banner()
        if not isinstance(content, str):
            raise TypeError("入口类 banner() 必须返回字符串")
        print(content)
        return
    print_banner(
        _application_name(main_type),
        _application_version(main_type),
        None if external_server else properties.server.host,
        None if external_server else properties.server.port,
    )
    try:
        banner_message = entry.banner_message  # type: ignore[union-attr]
    except AttributeError:
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
    entry: object | None = None,
    external_server: bool = False,
) -> Litestar:
    """装配框架和业务，并接入入口类声明的生命周期钩子。"""
    if not _is_main_type(main_type):
        raise TypeError("启动入口类必须使用 @LilywhiteMain 标记")
    package = _business_package(main_type)
    entry = main_type() if entry is None else entry
    try:
        logger_override = entry.override_logger  # type: ignore[attr-defined]
    except AttributeError:
        logger_override = None
    if logger_override is not None:
        if not callable(logger_override):
            raise TypeError("入口类 override_logger 必须是可调用方法")
        use_custom_logger(logger_override())
    framework = LilyWhiteApplication(
        properties,
        controller_packages=("lilywhite.controller",),
        business_package=package,
        managed_registries=_managed_registries(entry),
        optional_imports=_optional_imports(entry, properties),
        application_name=_application_name(main_type),
        external_server=external_server,
    )
    try:
        startup_hook = entry.on_startup  # type: ignore[attr-defined]
    except AttributeError:
        startup_hook = None
    if startup_hook is not None:
        if not callable(startup_hook):
            raise TypeError("入口类 on_startup 必须是可调用方法")
        framework.lifespan.register("entry_on_startup", "START")(startup_hook)
    try:
        shutdown_hook = entry.on_shutdown  # type: ignore[attr-defined]
    except AttributeError:
        shutdown_hook = None
    if shutdown_hook is not None:
        if not callable(shutdown_hook):
            raise TypeError("入口类 on_shutdown 必须是可调用方法")
        framework.lifespan.register("entry_on_shutdown", "STOP")(shutdown_hook)
    return framework.create_app()


def LilywhiteMain[T](target: type[T]) -> type[T]:
    """标记入口类并注入标准 ASGI 调用接口，不生成代理类型。"""
    target.__lilywhite_main__ = True  # type: ignore[attr-defined]
    target.__lilywhite_asgi_application__ = None  # type: ignore[attr-defined]

    async def asgi_call(self: object, scope: Scope, receive: Receive, send: Send) -> None:
        """缓存当前入口实例的 Litestar 应用并转发 ASGI 调用。"""
        application = self.__lilywhite_asgi_application__  # type: ignore[attr-defined]
        if not isinstance(application, Litestar):
            properties = ConfigLoader(Path("config.yaml")).load(_properties_type(type(self)))
            _print_entry_banner(type(self), properties, external_server=True, entry=self)
            application = _create_application(type(self), properties, entry=self, external_server=True)
            self.__lilywhite_asgi_application__ = application  # type: ignore[attr-defined]
        await application(scope, receive, send)

    target.__call__ = asgi_call  # type: ignore[method-assign]
    return target


def run(main_type: type[object], argv: list[str] | None = None) -> None:
    """从已标记入口类推导业务包，组合框架并启动 Uvicorn。"""
    if not _is_main_type(main_type):
        raise TypeError("启动入口类必须使用 @LilywhiteMain 标记")

    parser = argparse.ArgumentParser(description="LilyWhite Framework application")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument(
        "--log-level",
        type=str.upper,
        choices=("TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
    )
    parser.add_argument("--log-file", type=Path)
    parser.add_argument("--no-console", action="store_true")
    args = parser.parse_args(argv)

    properties = ConfigLoader(args.config).load(_properties_type(main_type))
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
        entry = main_type()
        _print_entry_banner(main_type, properties, entry=entry)
        application = _create_application(main_type, properties, entry=entry)
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
