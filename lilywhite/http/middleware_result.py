"""在 ASGI 中间件中直接发送 Litestar Response。"""

from litestar import Request, Response
from litestar.connection.base import empty_receive
from litestar.datastructures import State
from litestar.types import Scope, Send


async def send_response(scope: Scope, send: Send, response: Response[object]) -> None:
    """把现有 Response 转换为 ASGI 事件并发送，不手写 JSON 和响应头。"""
    request: Request[object, object, State] = Request(scope)
    asgi_response = response.to_asgi_response(None, request)
    await asgi_response(scope, empty_receive, send)


__all__ = ["send_response"]
