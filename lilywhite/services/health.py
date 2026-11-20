"""服务健康状态查询用例。"""

from ..decorators.service import service
from ..health import HealthCenter, HealthResult
from ..metrics import RequestMetrics, RequestMetricsResult
from .result import ServiceResult, success


@service
class HealthService:
    """聚合组件健康和请求指标。"""

    def __init__(self, health_center: HealthCenter, request_metrics: RequestMetrics) -> None:
        """保存应用级健康和指标组件。"""
        self._health_center = health_center
        self._request_metrics = request_metrics

    def get_health(self) -> ServiceResult[HealthResult]:
        """返回完整健康状态和请求指标。"""
        snapshot = self._health_center.snapshot()
        return success(
            HealthResult(
                status=snapshot.status,
                uptime_seconds=snapshot.uptime_seconds,
                components=snapshot.components,
                requests=self._request_metrics.snapshot(),
            )
        )

    def get_metrics(self) -> ServiceResult[RequestMetricsResult]:
        """返回当前请求指标快照。"""
        return success(self._request_metrics.snapshot())
