"""应用主类，只负责入口、运行时组合和启停日志。"""

from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager

from litestar import Litestar

from ..config import AppProperties
from ..logger import LoggerManager
from .exception_hooks import install_exception_hooks
from .http import create_http_app
from .runtime import ApplicationRuntime


class LilyWhiteApplication:
    """持有通用运行时并创建Litestar应用，不直接引用业务实现。"""

    def __init__(
        self,
        properties: AppProperties,
        *,
        backends: str | tuple[str, ...] = "memory",
        resources: Mapping[type[object], object] | None = None,
        controller_package: str = "lilywhite.controller",
        service_package: str = "lilywhite.services",
        storage_package: str = "lilywhite.storage",
    ) -> None:
        """初始化日志并自动收集配置、组件和生命周期。"""
        LoggerManager.initialize(properties.logging)
        install_exception_hooks()
        self._log = LoggerManager.get_logger("APP")
        self._log.info("logging initialized")
        self._backend = backends
        self._runtime = ApplicationRuntime(
            properties,
            backends=backends,
            resources=resources,
            service_package=service_package,
            storage_package=storage_package,
        )
        self.health_center = self._runtime.health_center
        self.request_metrics = self._runtime.request_metrics
        self.log_stream = self._runtime.log_stream
        self.lifespan = self._runtime.lifespan
        self._controller_package = controller_package

    def create_app(self) -> Litestar:
        """创建与当前运行时绑定的HTTP应用。"""
        return create_http_app(self._runtime, self._controller_package, self._application_lifespan)

    @asynccontextmanager
    async def _application_lifespan(self, _app: Litestar) -> AsyncGenerator[None]:
        """启动和关闭全部托管组件，并记录服务运行状态。"""
        try:
            await self.lifespan.start()
        except Exception as error:
            self._log.error("server startup failed type={}", type(error).__name__)
            raise

        self._log.info("server startup complete; service is running backend={}", self._backend)
        try:
            yield
        finally:
            await self.lifespan.stop()
            self._log.info("server shutdown complete")


__all__ = ["LilyWhiteApplication"]
