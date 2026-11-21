"""HTTP 路由指标 hook 与 ASGI 采集中间件。"""

import time
from typing import cast

from litestar import Request
from litestar.datastructures import State
from litestar.enums import ScopeType
from litestar.types import ASGIApp, Message, Receive, Scope, Send

from ...observability.metrics import RequestMetrics

_ROUTE_KEY = "_reuse_metrics_route"


def _route_name(scope: Scope) -> str:
    """使用路由模板生成有界指标键，未匹配请求统一归类。"""
    method = scope.get("method", "UNKNOWN")
    template = scope.get("path_template")
    return f"{method} {template}" if isinstance(template, str) else f"{method} <unmatched>"


class RequestMetricsHooks:
    """在路由匹配完成后开始接口级并发计数。"""

    def __init__(self, metrics: RequestMetrics) -> None:
        """保存进程级指标存储。"""
        self._metrics = metrics

    def before_request(self, request: Request[object, object, State]) -> None:
        """记录 path_template 并增加对应接口并发数。"""
        route = _route_name(request.scope)
        scope = cast(dict[str, object], request.scope)
        scope[_ROUTE_KEY] = route
        self._metrics.request_started(route)


class RequestMetricsMiddleware:
    """记录已匹配路由的请求耗时和响应状态。"""

    def __init__(self, app: ASGIApp, metrics: RequestMetrics) -> None:
        """保存下一层 ASGI 应用和指标存储。"""
        self.app = app
        self._metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """采集一次 HTTP 请求，异常时按 500 记录并继续抛出。"""
        if scope["type"] != ScopeType.HTTP:
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status = 500

        async def measured_send(message: Message) -> None:
            """捕获响应状态并继续发送。"""
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, measured_send)
        finally:
            scope_values = cast(dict[str, object], scope)
            route = scope_values.get(_ROUTE_KEY)
            if not isinstance(route, str):
                route = _route_name(scope)
                self._metrics.request_started(route)
            elapsed_ms = (time.perf_counter() - started) * 1000
            self._metrics.request_finished(route, elapsed_ms, status)
