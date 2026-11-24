"""Litestar 路由、依赖、中间件与可选 HTTP 扩展装配。"""

from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from inspect import Parameter, signature
from typing import cast, get_type_hints

from litestar import Litestar
from litestar.app import DEFAULT_OPENAPI_CONFIG
from litestar.config.cors import CORSConfig
from litestar.middleware import DefineMiddleware
from litestar.openapi.config import OpenAPIConfig
from litestar.types import ASGIApp, ExceptionHandler

from ..decorators.exception_handler import registered_exception_handlers
from ..decorators.middleware import registered_middlewares
from ..http.middleware.metrics import RequestMetricsHooks, RequestMetricsMiddleware
from .container import DependencyContainer
from .discovery import discover_business_controllers, discover_controllers, discover_websocket_controllers
from .runtime import ApplicationRuntime
from .scope import RequestScopeMiddleware

type ApplicationLifespan = Callable[[Litestar], AbstractAsyncContextManager[None]]


def _registered_exception_handlers(
    runtime: ApplicationRuntime,
) -> dict[int | type[Exception], ExceptionHandler[Exception]]:
    """绑定独立函数和 DI 处理器组，形成 Litestar 异常映射。"""
    if runtime.business_package is None:
        return {}
    handlers: dict[int | type[Exception], ExceptionHandler[Exception]] = {}
    for registration in registered_exception_handlers((runtime.business_package,)):
        handler = registration.handler
        owner_type = registration.owner_type
        if owner_type is not None:
            owner = runtime.container.resolve(owner_type)
            bound = handler.__get__(owner, owner_type)
            handlers[registration.exception_type] = cast("ExceptionHandler[Exception]", bound)
        else:
            handlers[registration.exception_type] = cast("ExceptionHandler[Exception]", handler)
    return handlers


def _middleware_dependencies(
    container: DependencyContainer,
    middleware_type: type[object],
) -> dict[str, object]:
    """除下一层 app 外，按构造器注解注入 Singleton 依赖。"""
    constructor = middleware_type.__init__
    hints = get_type_hints(constructor, include_extras=True)
    dependencies: dict[str, object] = {}
    for parameter in list(signature(constructor).parameters.values())[2:]:
        location = f"{middleware_type.__module__}.{middleware_type.__qualname__}.{parameter.name}"
        if parameter.kind not in (Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY):
            raise TypeError(f"中间件依赖参数不受支持：{location}")
        dependency = container._dependency_parameter(
            hints.get(parameter.name), "中间件构造器参数", location, parameter.name
        )
        dependencies[parameter.name] = container._resolve_singleton(dependency.key)
    return dependencies


def _registered_middleware(runtime: ApplicationRuntime) -> list[DefineMiddleware]:
    """按声明顺序把业务中间件转换为 Litestar DefineMiddleware。"""
    if runtime.business_package is None:
        return []
    return [
        DefineMiddleware(
            cast("Callable[..., ASGIApp]", registration.middleware_type),
            **_middleware_dependencies(runtime.container, registration.middleware_type),
        )
        for registration in registered_middlewares((runtime.business_package,))
    ]


def create_http_app(
    runtime: ApplicationRuntime,
    controller_packages: tuple[str, ...],
    lifespan: ApplicationLifespan,
    *,
    exception_handlers: Mapping[int | type[Exception], ExceptionHandler[Exception]] | None = None,
    openapi_config: OpenAPIConfig | None = None,
) -> Litestar:
    """使用运行时依赖、自动发现路由和项目级 HTTP 配置创建应用。"""
    route_handlers = [
        controller
        for controller_package in controller_packages
        for controller in (
            *discover_controllers(controller_package),
            *discover_websocket_controllers(controller_package),
        )
    ]
    if runtime.business_package is not None:
        route_handlers.extend(
            (
                *discover_business_controllers(
                    runtime.business_package,
                    properties=runtime.properties,
                    managed_registries=runtime.managed_registries,
                    optional_imports=runtime.optional_imports,
                ),
                *discover_websocket_controllers(runtime.business_package),
            )
        )
    handlers: dict[int | type[Exception], ExceptionHandler[Exception]] = {}
    handlers.update(_registered_exception_handlers(runtime))
    handlers.update(exception_handlers or {})
    return Litestar(
        route_handlers=route_handlers,
        dependencies=runtime.container.litestar_dependencies(),
        lifespan=[lifespan],
        middleware=[
            DefineMiddleware(RequestMetricsMiddleware, metrics=runtime.request_metrics),
            DefineMiddleware(RequestScopeMiddleware, container=runtime.container),
            *_registered_middleware(runtime),
        ],
        before_request=RequestMetricsHooks(runtime.request_metrics).before_request,
        exception_handlers=handlers,
        openapi_config=openapi_config or DEFAULT_OPENAPI_CONFIG,
        cors_config=(
            CORSConfig(allow_origins=list(runtime.cors_allow_origins)) if runtime.cors_allow_origins else None
        ),
        logging_config=None,
    )


__all__ = ["ApplicationLifespan", "create_http_app"]
