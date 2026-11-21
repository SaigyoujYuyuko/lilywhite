"""服务健康与请求指标 HTTP 入口。"""

from litestar import Controller, Request, Response, get
from litestar.datastructures import State
from litestar.di import NamedDependency
from litestar.response.sse import ServerSentEvent

from ..decorators.controller import controller
from ..health import HealthStatusType
from ..services.health import HealthService
from ..services.log import LogService
from .result import not_found, ok, sse, too_many_requests, unauthorized


@controller("/")
class OperationsController(Controller):
    """运维查询接口。"""

    @get("/healthz")
    async def health(self, health_service: NamedDependency[HealthService]) -> Response[object]:
        """返回完整健康状态，非健康状态使用 503。"""
        result = health_service.get_health()
        status = 200 if result.data is not None and result.data.status is HealthStatusType.HEALTHY else 503
        return ok(result.data, status=status)

    @get("/metrics")
    async def metrics(self, health_service: NamedDependency[HealthService]) -> Response[object]:
        """返回全局和每个路由模板的请求指标。"""
        result = health_service.get_metrics()
        return ok(result.data)

    @get("/logs/stream")
    async def logs(
        self,
        request: Request[object, object, State],
        log_service: NamedDependency[LogService],
    ) -> Response[object] | ServerSentEvent:
        """验证独立运维Bearer并流式返回日志事件。"""
        result = log_service.subscribe(request.headers.get("authorization", ""))
        if result.data is None:
            if result.error is not None and result.error.code == "log_stream_disabled":
                return not_found(message="Log stream is not configured.")
            if result.error is not None and result.error.code == "log_stream_busy":
                return too_many_requests(message="Too many active log subscriptions.")
            return unauthorized(message="Authentication required.")
        return sse(result.data.events(), event_type="log", event_id=lambda event: event.id)
