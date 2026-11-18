"""Controller 统一的 HTTP 结果构造。"""

from collections.abc import AsyncIterator

import msgspec
from litestar import Response
from litestar.enums import MediaType
from litestar.response.sse import ServerSentEvent, ServerSentEventMessage

from ..domain.json import as_json_object
from ..observability import LogEvent

type JsonValue = bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None
type JsonObject = dict[str, JsonValue]


class HttpResult(msgspec.Struct, frozen=True):
    """统一 HTTP JSON 响应信封，body 在构造时完成动态值收窄。"""

    status: int
    body: object | None
    error_message: str

    def __post_init__(self) -> None:
        """验证动态body，同时让OpenAPI将其生成为自由JSON对象。"""
        if self.body is not None:
            as_json_object(self.body)


def response[T](
    content: T,
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
    media_type: MediaType | str = MediaType.JSON,
) -> Response[T]:
    """构造指定内容、状态码、Header 和媒体类型的响应。"""
    return Response(content, status_code=status, headers=headers, media_type=media_type)


def log_stream(events: AsyncIterator[LogEvent | None]) -> ServerSentEvent:
    """把日志订阅编码为带心跳和重连提示的SSE响应。"""

    async def messages() -> AsyncIterator[ServerSentEventMessage]:
        """将日志模型转换为事件，将空事件转换为注释心跳。"""
        async for event in events:
            if event is None:
                yield ServerSentEventMessage(comment="keep-alive")
            else:
                yield ServerSentEventMessage(
                    data=msgspec.json.encode(event),
                    event="log",
                    id=event.id,
                )

    return ServerSentEvent(
        messages(),
        event_type="log",
        retry_duration=3000,
        headers={"Cache-Control": "no-store"},
    )


def ok(body: JsonObject | None = None, *, status: int = 200) -> Response[HttpResult]:
    """返回禁止缓存的成功响应。"""
    return response(
        HttpResult(status=0, body=body, error_message=""),
        status=status,
        headers={"Cache-Control": "no-store"},
    )


def created(body: JsonObject | None = None, *, headers: dict[str, str] | None = None) -> Response[HttpResult]:
    """返回201已创建响应和可选资源位置。"""
    result = ok(body, status=201)
    result.headers.update(headers or {})
    return result


def accepted(body: JsonObject | None = None) -> Response[HttpResult]:
    """返回 202 已接受响应。"""
    return ok(body, status=202)


def no_content() -> Response[None]:
    """返回 204 无内容响应。"""
    return response(None, status=204, headers={"Cache-Control": "no-store"})


def http_error(status: int = 400, message: str = "", body: JsonObject | None = None) -> Response[HttpResult]:
    """返回使用相同 HTTP 状态和业务状态的错误响应。"""
    return response(
        HttpResult(status=status, body=body, error_message=message),
        status=status,
        headers={"Cache-Control": "no-store"},
    )


def bad_request(message: str = "", body: JsonObject | None = None) -> Response[HttpResult]:
    """返回 400 请求错误。"""
    return http_error(400, message, body)


def unauthorized(message: str = "", body: JsonObject | None = None) -> Response[HttpResult]:
    """返回 401 未授权响应和 Bearer 挑战。"""
    result = http_error(401, message, body)
    result.headers["WWW-Authenticate"] = "Bearer"
    return result


def forbidden(message: str = "", body: JsonObject | None = None) -> Response[HttpResult]:
    """返回 403 禁止访问响应。"""
    return http_error(403, message, body)


def not_found(message: str = "", body: JsonObject | None = None) -> Response[HttpResult]:
    """返回 404 资源不存在响应。"""
    return http_error(404, message, body)


def method_not_allowed(
    message: str = "",
    body: JsonObject | None = None,
    *,
    allow: str | None = None,
) -> Response[HttpResult]:
    """返回 405 方法不允许响应。"""
    result = http_error(405, message, body)
    if allow is not None:
        result.headers["Allow"] = allow
    return result


def conflict(message: str = "", body: JsonObject | None = None) -> Response[HttpResult]:
    """返回 409 资源冲突响应。"""
    return http_error(409, message, body)


def payload_too_large(message: str = "", body: JsonObject | None = None) -> Response[HttpResult]:
    """返回 413 请求体过大响应。"""
    return http_error(413, message, body)


def unsupported_media_type(message: str = "", body: JsonObject | None = None) -> Response[HttpResult]:
    """返回 415 媒体类型不支持响应。"""
    return http_error(415, message, body)


def too_many_requests(message: str = "", body: JsonObject | None = None) -> Response[HttpResult]:
    """返回 429 请求过多响应。"""
    return http_error(429, message, body)


def internal_server_error(message: str = "", body: JsonObject | None = None) -> Response[HttpResult]:
    """返回 500 服务器内部错误响应。"""
    return http_error(500, message, body)


def not_implemented(message: str = "", body: JsonObject | None = None) -> Response[HttpResult]:
    """返回 501 功能未实现响应。"""
    return http_error(501, message, body)


def bad_gateway(message: str = "", body: JsonObject | None = None) -> Response[HttpResult]:
    """返回 502 错误网关响应。"""
    return http_error(502, message, body)


def service_unavailable(message: str = "", body: JsonObject | None = None) -> Response[HttpResult]:
    """返回 503 服务不可用响应。"""
    return http_error(503, message, body)
