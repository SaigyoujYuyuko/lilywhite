"""有界 HTTP 请求指标与只读快照。"""

import math
import threading
from collections import deque

import msgspec


class RouteMetricsResult(msgspec.Struct, frozen=True):
    """单个路由模板的请求指标。"""

    active_requests: int
    max_active_requests: int
    total_requests: int
    error_count: int
    p50_ms: float
    p99_ms: float


class RequestMetricsResult(msgspec.Struct, frozen=True):
    """进程级请求指标快照。"""

    active_requests: int
    total_requests: int
    error_count: int
    error_rate: float
    p50_ms: float
    p99_ms: float
    routes: dict[str, RouteMetricsResult]


class _RouteMetrics:
    """单个路由的可变滑动窗口。"""

    def __init__(self, window_size: int) -> None:
        """创建有界延迟窗口和计数器。"""
        self.active_requests = 0
        self.max_active_requests = 0
        self.total_requests = 0
        self.error_count = 0
        self.latencies: deque[float] = deque(maxlen=window_size)


def _percentile(latencies: list[float], quantile: float) -> float:
    """使用最近秩计算滑动窗口分位数。"""
    if not latencies:
        return 0.0
    ordered = sorted(latencies)
    index = max(0, math.ceil(len(ordered) * quantile) - 1)
    return round(ordered[index], 3)


class RequestMetrics:
    """线程安全地聚合请求并发、错误和有限延迟样本。"""

    def __init__(self, window_size: int = 4096) -> None:
        """设置全局和每个路由的延迟窗口上限。"""
        if window_size <= 0:
            raise ValueError("指标窗口必须大于 0")
        self._window_size = window_size
        self._lock = threading.Lock()
        self._active_requests = 0
        self._total_requests = 0
        self._error_count = 0
        self._latencies: deque[float] = deque(maxlen=window_size)
        self._routes: dict[str, _RouteMetrics] = {}

    def request_started(self, route: str) -> None:
        """增加全局和路由模板的当前并发数。"""
        with self._lock:
            route_metrics = self._routes.setdefault(route, _RouteMetrics(self._window_size))
            self._active_requests += 1
            route_metrics.active_requests += 1
            route_metrics.max_active_requests = max(
                route_metrics.max_active_requests,
                route_metrics.active_requests,
            )

    def request_finished(self, route: str, elapsed_ms: float, status: int) -> None:
        """减少并发并记录一次完成请求。"""
        with self._lock:
            route_metrics = self._routes[route]
            self._active_requests -= 1
            route_metrics.active_requests -= 1
            self._total_requests += 1
            route_metrics.total_requests += 1
            if status >= 400:
                self._error_count += 1
                route_metrics.error_count += 1
            self._latencies.append(elapsed_ms)
            route_metrics.latencies.append(elapsed_ms)

    def snapshot(self) -> RequestMetricsResult:
        """复制有界样本并计算全局与路由分位数。"""
        with self._lock:
            latencies = list(self._latencies)
            routes = {
                name: (
                    metrics.active_requests,
                    metrics.max_active_requests,
                    metrics.total_requests,
                    metrics.error_count,
                    list(metrics.latencies),
                )
                for name, metrics in self._routes.items()
            }
            active_requests = self._active_requests
            total_requests = self._total_requests
            error_count = self._error_count

        route_results = {
            name: RouteMetricsResult(
                active_requests=values[0],
                max_active_requests=values[1],
                total_requests=values[2],
                error_count=values[3],
                p50_ms=_percentile(values[4], 0.50),
                p99_ms=_percentile(values[4], 0.99),
            )
            for name, values in sorted(routes.items())
        }
        return RequestMetricsResult(
            active_requests=active_requests,
            total_requests=total_requests,
            error_count=error_count,
            error_rate=error_count / total_requests if total_requests else 0.0,
            p50_ms=_percentile(latencies, 0.50),
            p99_ms=_percentile(latencies, 0.99),
            routes=route_results,
        )
