"""HTTP 请求结束后的 Scoped 资源清理中间件。"""

from typing import cast

from litestar.enums import ScopeType
from litestar.types import ASGIApp, Receive, Scope, Send

from .container import DependencyContainer, DependencyScope


class RequestScopeMiddleware:
    """在响应流完整结束或请求异常后关闭当前请求的 Scoped 资源。"""

    def __init__(self, app: ASGIApp, container: DependencyContainer) -> None:
        self.app = app
        self._container = container

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """请求结束后释放资源；非 HTTP 协议直接交给后续应用。"""
        if scope["type"] != ScopeType.HTTP:
            await self.app(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        finally:
            scope_values = cast(dict[str, object], scope)
            dependency_scope = scope_values.get(self._container.request_scope_key)
            if isinstance(dependency_scope, DependencyScope):
                await dependency_scope.close()


__all__ = ["RequestScopeMiddleware"]
