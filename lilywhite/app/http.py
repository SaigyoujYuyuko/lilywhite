"""Litestar 路由、依赖和中间件装配。"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from litestar import Litestar
from litestar.config.cors import CORSConfig
from litestar.middleware import DefineMiddleware

from ..controller.middleware.metrics import RequestMetricsHooks, RequestMetricsMiddleware
from .discovery import discover_controllers
from .runtime import ApplicationRuntime

type ApplicationLifespan = Callable[[Litestar], AbstractAsyncContextManager[None]]


def create_http_app(
    runtime: ApplicationRuntime,
    controller_package: str,
    lifespan: ApplicationLifespan,
) -> Litestar:
    """使用运行时依赖和自动发现的Controller创建HTTP应用。"""
    return Litestar(
        route_handlers=discover_controllers(controller_package),
        dependencies=runtime.container.litestar_dependencies(),
        lifespan=[lifespan],
        middleware=[DefineMiddleware(RequestMetricsMiddleware, metrics=runtime.request_metrics)],
        before_request=RequestMetricsHooks(runtime.request_metrics).before_request,
        cors_config=(
            CORSConfig(allow_origins=list(runtime.cors_allow_origins)) if runtime.cors_allow_origins else None
        ),
        logging_config=None,
    )


__all__ = ["ApplicationLifespan", "create_http_app"]
