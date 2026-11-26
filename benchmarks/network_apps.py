"""真实网络基准使用的 LilyWhite 与原生 Litestar 对称应用。"""

from collections.abc import AsyncIterator

from litestar import Controller, Litestar, get
from litestar.config.cors import CORSConfig
from litestar.di import NamedDependency, Provide
from litestar.middleware import DefineMiddleware

from lilywhite import AppProperties, LilyWhiteApplication, component, controller, service
from lilywhite.http.middleware.metrics import RequestMetricsHooks, RequestMetricsMiddleware
from lilywhite.observability.metrics import RequestMetrics
from lilywhite.utils.registry import LifetimeType


@component(lifetime=LifetimeType.SCOPED)
class NetworkResource:
    """模拟每个请求创建并释放的 Scoped 资源。"""

    active = True

    async def close(self) -> None:
        """标记当前请求资源已经释放。"""
        self.active = False


@component(lifetime=LifetimeType.TRANSIENT)
class NetworkOption:
    """模拟每个请求独立创建的轻量配置对象。"""


@service(lifetime=LifetimeType.SCOPED)
class NetworkService:
    """组合与原生对照组相同的两个下游依赖。"""

    def __init__(self, resource: NetworkResource, option: NetworkOption) -> None:
        self.resource = resource
        self.option = option


@controller("/")
class NetworkController(Controller):
    """通过 LilyWhite AST 发现和 NamedDependency 进入真实请求链路。"""

    @get("/benchmark")
    async def benchmark(self, network_service: NamedDependency[NetworkService]) -> dict[str, bool]:
        """返回与实际依赖状态相关的最小 JSON 响应。"""
        return {"active": network_service.resource.active}


def create_lilywhite_app() -> Litestar:
    """创建包含标准中间件、CORS、指标和 DI 的完整 LilyWhite 应用。"""
    properties = AppProperties().override(logging={"console": False})
    return LilyWhiteApplication(
        properties,
        controller_packages=(),
        business_package="benchmarks",
        application_name="LilyWhite Network Benchmark",
    ).create_app()


async def _native_resource() -> AsyncIterator[NetworkResource]:
    """通过 Litestar 原生生成器依赖自动释放请求资源。"""
    resource = NetworkResource()
    try:
        yield resource
    finally:
        await resource.close()


def _native_option() -> NetworkOption:
    """提供原生 Transient 依赖。"""
    return NetworkOption()


def _native_service(resource: NetworkResource, option: NetworkOption) -> NetworkService:
    """通过原生 Litestar DI 构造业务 Service。"""
    return NetworkService(resource, option)


@get("/benchmark")
async def native_benchmark(network_service: NetworkService) -> dict[str, bool]:
    """执行与 LilyWhite 相同的原生类型注入路由。"""
    return {"active": network_service.resource.active}


def create_native_app() -> Litestar:
    """创建具有相同指标、CORS 和业务依赖语义的原生 Litestar 应用。"""
    properties = AppProperties()
    metrics = RequestMetrics(properties.operations.metrics_window_size)
    return Litestar(
        route_handlers=[native_benchmark],
        dependencies={
            "resource": Provide(_native_resource),
            "option": Provide(_native_option, sync_to_thread=False),
            "network_service": Provide(_native_service, sync_to_thread=False),
        },
        middleware=[DefineMiddleware(RequestMetricsMiddleware, metrics=metrics)],
        before_request=RequestMetricsHooks(metrics).before_request,
        cors_config=CORSConfig(allow_origins=list(properties.server.cors.allow_origins)),
        logging_config=None,
    )


__all__ = ["create_lilywhite_app", "create_native_app"]
