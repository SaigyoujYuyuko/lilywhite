"""应用主类，只负责入口、运行时组合和启停日志。"""

from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager

from litestar import Litestar
from litestar.openapi.config import OpenAPIConfig
from litestar.types import ExceptionHandler

from ..banner import server_url
from ..config import AppProperties
from ..logger import LoggerManager
from ..utils.registry import ManagedRegistrySelection
from .exception_hooks import install_exception_hooks
from .http import create_http_app
from .runtime import ApplicationRuntime


class LilyWhiteApplication:
    """持有通用运行时并创建Litestar应用，不直接引用业务实现。"""

    def __init__(
        self,
        properties: AppProperties,
        *,
        resources: Mapping[type[object], object] | None = None,
        controller_packages: tuple[str, ...] = ("lilywhite.controller",),
        business_package: str | None = None,
        managed_registries: ManagedRegistrySelection = (),
        optional_imports: tuple[str, ...] = (),
        application_name: str = "LilyWhite Application",
        external_server: bool = False,
        exception_handlers: Mapping[int | type[Exception], ExceptionHandler[Exception]] | None = None,
        openapi_config: OpenAPIConfig | None = None,
    ) -> None:
        """初始化日志、依赖容器和项目级 HTTP 扩展。"""
        LoggerManager.initialize(properties.logging)
        install_exception_hooks()
        self._log = LoggerManager.get_logger("APP")
        self._log.info("logging initialized")
        self._application_name = application_name
        self._url = (
            "external ASGI server"
            if external_server
            else server_url(properties.server.host, properties.server.port)
        )
        self._runtime = ApplicationRuntime(
            properties,
            resources=resources,
            business_package=business_package,
            managed_registries=managed_registries,
            optional_imports=optional_imports,
        )
        self.container = self._runtime.container
        self.health_center = self._runtime.health_center
        self.request_metrics = self._runtime.request_metrics
        self.log_stream = self._runtime.log_stream
        self.lifespan = self._runtime.lifespan
        self._controller_packages = controller_packages
        self._exception_handlers = exception_handlers
        self._openapi_config = openapi_config

    def create_app(self) -> Litestar:
        """创建与当前运行时绑定的HTTP应用。"""
        return create_http_app(
            self._runtime,
            self._controller_packages,
            self._application_lifespan,
            exception_handlers=self._exception_handlers,
            openapi_config=self._openapi_config,
        )

    @asynccontextmanager
    async def _application_lifespan(self, _app: Litestar) -> AsyncGenerator[None]:
        """启动和关闭全部托管组件，并记录服务运行状态。"""
        try:
            await self.lifespan.start()
        except Exception as error:
            self._log.error("server startup failed type={}", type(error).__name__)
            raise

        self._log.info("{}: server is running on: {}", self._application_name, self._url)
        try:
            yield
        finally:
            await self.lifespan.stop()
            self._log.info("server shutdown complete")


__all__ = ["LilyWhiteApplication"]
