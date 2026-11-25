"""自动收集配置、组件和生命周期的运行时组合根。"""

from collections.abc import Mapping

from ..config import AppProperties
from ..lifecycle import ManagedComponent
from ..observability import LogStream
from ..observability.health import HealthCenter
from ..observability.metrics import RequestMetrics
from ..utils.registry import ManagedRegistrySelection
from .DI.container import create_container
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
        optional_imports: tuple[str, ...] = (),
    ) -> None:
        """创建运行时并自动注册当前业务包与框架组件。"""
        self.business_package = business_package
        self.properties = properties
        self.managed_registries = managed_registries
        self.optional_imports = optional_imports
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
            optional_imports=optional_imports,
        )
        self._active_components: dict[str, ManagedComponent] = {}
        self.lifespan = LifespanManager()
        self.lifespan.register("health", "START")(self.health_center.start)
        self.lifespan.register("health", "STOP")(self.health_center.stop)
        self.lifespan.register("dependency_container", "START")(self.container.build_async)
        self.lifespan.register("components", "START")(self._start_components)
        self.lifespan.register("components", "STOP")(self._stop_components)

    async def _start_components(self) -> None:
        """在异步 Bean 就绪后启动全部组件，并回滚已经启动的部分。"""
        try:
            for name, component in self.container.managed_component_registrations():
                await self._start_component(name, component)
                self._active_components[name] = component
        except Exception as start_error:
            try:
                await self._stop_components()
            except Exception as stop_error:  # noqa: BLE001
                raise ExceptionGroup(
                    "组件启动失败后的资源回滚也失败", [start_error, stop_error]
                ) from start_error
            raise

    async def _stop_components(self) -> None:
        """逆序关闭当前已启动组件，并继续处理后续关闭错误。"""
        errors: list[Exception] = []
        for name in reversed(tuple(self._active_components)):
            component = self._active_components.pop(name)
            try:
                await self._stop_component(name, component)
            except Exception as error:  # noqa: BLE001
                errors.append(error)
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise ExceptionGroup("组件关闭失败", errors)

    async def _start_component(self, name: str, component: ManagedComponent) -> None:
        """初始化失败时先释放当前组件，再由统一分组回滚先前组件。"""
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
