"""Controller 的 HTTP 响应构造工具。"""

from collections.abc import AsyncIterator, Callable

import msgspec
from litestar import Response
from litestar.enums import MediaType
from litestar.response.sse import ServerSentEvent, ServerSentEventMessage

type JsonValue = bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None
type JsonObject = dict[str, JsonValue]
type ResponseContent[T] = T | dict[str, object] | None


def _response_content[T](content: T | None, params: dict[str, object]) -> ResponseContent[T]:
    """选择完整响应模型或关键字字段，拒绝两种内容来源混用。"""
    if content is not None and params:
        raise ValueError("content 与关键字响应字段不能同时传入")
    if params:
        return params
    return content


def response[T](
    content: T,
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
    media_type: MediaType | str = MediaType.JSON,
) -> Response[T]:
    """构造指定内容、状态码、Header 和媒体类型的响应。"""
    return Response(content, status_code=status, headers=headers, media_type=media_type)


def stream[T](
    events: AsyncIterator[T | None],
    *,
    event_type: str = "message",
    event_id: Callable[[T], str | int | None] | None = None,
    retry_duration: int = 3000,
    headers: dict[str, str] | None = None,
) -> ServerSentEvent:
    """把任意事件流编码为 SSE，空事件作为注释心跳。"""

    async def messages() -> AsyncIterator[ServerSentEventMessage]:
        """编码事件数据，并按需附加事件 ID。"""
        async for event in events:
            if event is None:
                yield ServerSentEventMessage(comment="keep-alive")
            else:
                yield ServerSentEventMessage(
                    data=msgspec.json.encode(event),
                    event=event_type,
                    id=event_id(event) if event_id is not None else None,
                )

    return ServerSentEvent(
        messages(),
        event_type=event_type,
        retry_duration=retry_duration,
        headers=headers if headers is not None else {"Cache-Control": "no-store"},
    )


def ok[T](
    content: T | None = None,
    *,
    status: int = 200,
    **params: object,
) -> Response[ResponseContent[T]]:
    """返回成功响应，内容可以是完整模型或关键字字段。"""
    return response(
        _response_content(content, params),
        status=status,
        headers={"Cache-Control": "no-store"},
    )


def created[T](
    content: T | None = None,
    *,
    headers: dict[str, str] | None = None,
    **params: object,
) -> Response[ResponseContent[T]]:
    """返回201已创建响应和可选资源位置。"""
    result = ok(content, status=201, **params)
    result.headers.update(headers or {})
    return result


def accepted[T](content: T | None = None, **params: object) -> Response[ResponseContent[T]]:
    """返回 202 已接受响应。"""
    return ok(content, status=202, **params)


def no_content() -> Response[None]:
    """返回 204 无内容响应。"""
    return response(None, status=204, headers={"Cache-Control": "no-store"})


def http_error[T](
    status: int = 400,
    content: T | None = None,
    **params: object,
) -> Response[ResponseContent[T]]:
    """返回指定 HTTP 状态和业务内容的错误响应。"""
    return response(
        _response_content(content, params),
        status=status,
        headers={"Cache-Control": "no-store"},
    )


def bad_request[T](content: T | None = None, **params: object) -> Response[ResponseContent[T]]:
    """返回 400 请求错误。"""
    return http_error(400, content, **params)


def unauthorized[T](content: T | None = None, **params: object) -> Response[ResponseContent[T]]:
    """返回 401 未授权响应和 Bearer 挑战。"""
    result = http_error(401, content, **params)
    result.headers["WWW-Authenticate"] = "Bearer"
    return result


def forbidden[T](content: T | None = None, **params: object) -> Response[ResponseContent[T]]:
    """返回 403 禁止访问响应。"""
    return http_error(403, content, **params)


def not_found[T](content: T | None = None, **params: object) -> Response[ResponseContent[T]]:
    """返回 404 资源不存在响应。"""
    return http_error(404, content, **params)


def method_not_allowed[T](
    content: T | None = None,
    *,
    allow: str | None = None,
    **params: object,
) -> Response[ResponseContent[T]]:
    """返回 405 方法不允许响应。"""
    result = http_error(405, content, **params)
    if allow is not None:
        result.headers["Allow"] = allow
    return result


def conflict[T](content: T | None = None, **params: object) -> Response[ResponseContent[T]]:
    """返回 409 资源冲突响应。"""
    return http_error(409, content, **params)


def payload_too_large[T](content: T | None = None, **params: object) -> Response[ResponseContent[T]]:
    """返回 413 请求体过大响应。"""
    return http_error(413, content, **params)


def unsupported_media_type[T](content: T | None = None, **params: object) -> Response[ResponseContent[T]]:
    """返回 415 媒体类型不支持响应。"""
    return http_error(415, content, **params)


def too_many_requests[T](content: T | None = None, **params: object) -> Response[ResponseContent[T]]:
    """返回 429 请求过多响应。"""
    return http_error(429, content, **params)


def internal_server_error[T](content: T | None = None, **params: object) -> Response[ResponseContent[T]]:
    """返回 500 服务器内部错误响应。"""
    return http_error(500, content, **params)


def not_implemented[T](content: T | None = None, **params: object) -> Response[ResponseContent[T]]:
    """返回 501 功能未实现响应。"""
    return http_error(501, content, **params)


def bad_gateway[T](content: T | None = None, **params: object) -> Response[ResponseContent[T]]:
    """返回 502 错误网关响应。"""
    return http_error(502, content, **params)


def service_unavailable[T](content: T | None = None, **params: object) -> Response[ResponseContent[T]]:
    """返回 503 服务不可用响应。"""
    return http_error(503, content, **params)
