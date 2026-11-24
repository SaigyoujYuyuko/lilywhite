"""中间件直接发送 Litestar Response 的真实 HTTP 测试。"""

from litestar import Litestar, get
from litestar.middleware import DefineMiddleware
from litestar.testing import TestClient
from litestar.types import ASGIApp, Receive, Scope, Send

from lilywhite.http.middleware_result import send_response
from lilywhite.http.result import unauthorized


class EarlyResponseMiddleware:
    """在命中路径时直接返回响应，其余路径交给路由。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] == "/blocked":
            await send_response(scope, send, unauthorized(message="需要有效的 API Token"))
            return
        await self.app(scope, receive, send)


@get("/blocked")
async def blocked() -> dict[str, bool]:
    """提前响应时不应到达这个路由。"""
    return {"reached": True}


@get("/open")
async def opened() -> dict[str, bool]:
    """未命中提前响应的路径应正常执行。"""
    return {"reached": True}


def test_send_response_short_circuits_middleware_with_existing_response() -> None:
    """中间件应复用 unauthorized 的状态、Unicode JSON 和特殊响应头。"""
    application = Litestar(
        route_handlers=[blocked, opened],
        middleware=[DefineMiddleware(EarlyResponseMiddleware)],
    )

    with TestClient(application) as client:
        blocked_response = client.get("/blocked")
        open_response = client.get("/open")

    assert blocked_response.status_code == 401
    assert blocked_response.json() == {"message": "需要有效的 API Token"}
    assert blocked_response.headers["WWW-Authenticate"] == "Bearer"
    assert blocked_response.headers["Content-Type"].startswith("application/json")
    assert int(blocked_response.headers["Content-Length"]) == len(blocked_response.content)
    assert open_response.status_code == 200
    assert open_response.json() == {"reached": True}
