"""自动收集配置、组件和生命周期的运行时组合根。"""

from collections.abc import Mapping

from ..config import AppProperties
from ..health import HealthCenter
from ..lifecycle import ManagedComponent
from ..metrics import RequestMetrics
from ..observability import LogStream
from ..utils.registry import ManagedRegistrySelection
from .container import create_container
from .lifespan import LifespanManager


class ApplicationRuntime:
    """持有依赖容器、观测组件和统一生命周期，不认识具体业务实现。"""

    def __init__(
        self,
        properties: AppProperties,
        *,
        resources: Mapping[type[object], object] | None = None,
        business_package: str | None = None,
        managed_registries: ManagedRegistrySelection = (),
    ) -> None:
        """创建运行时并自动注册当前业务包与框架组件。"""
        self.business_package = business_package
        self.properties = properties
        self.managed_registries = managed_registries
        self.health_center = HealthCenter()
        self.request_metrics = RequestMetrics(properties.operations.metrics_window_size)
        self.cors_allow_origins = properties.server.cors.allow_origins
        self.log_stream = LogStream(properties.logging.level, properties.logging.third_party_level)
        runtime_resources = dict(resources or {})
        runtime_resources[HealthCenter] = self.health_center
        runtime_resources[RequestMetrics] = self.request_metrics
        runtime_resources[LogStream] = self.log_stream
        self.container = create_container(
            properties=properties,
            business_package=business_package,
            resources=runtime_resources,
            managed_registries=managed_registries,
        )
        self.lifespan = LifespanManager()
        self.lifespan.register("health", "START")(self.health_center.start)
        self.lifespan.register("health", "STOP")(self.health_center.stop)
        for name, component in self.container.managed_component_registrations():
            self._register_component(name, component)

    def _register_component(self, name: str, component: ManagedComponent) -> None:
        """按包含限定名的组件名称注册启动、关闭和健康状态。"""
        self.lifespan.register(name, "START")(lambda: self._start_component(name, component))
        self.lifespan.register(name, "STOP")(lambda: self._stop_component(name, component))

    async def _start_component(self, name: str, component: ManagedComponent) -> None:
        """初始化失败时先释放当前组件，再由 LifespanManager 回滚先前组件。"""
        try:
            await component.initialize()
        except Exception as start_error:
            try:
                await component.close()
            except Exception as close_error:  # noqa: BLE001
                raise ExceptionGroup(
                    f"组件 {name} 初始化和回滚均失败", [start_error, close_error]
                ) from start_error
            finally:
                self.health_center.set_component(name, False)
            raise
        self.health_center.set_component(name, True)

    async def _stop_component(self, name: str, component: ManagedComponent) -> None:
        """关闭组件并保留可诊断的健康状态。"""
        await component.close()
        self.health_center.set_component(name, False)


__all__ = ["ApplicationRuntime"]
