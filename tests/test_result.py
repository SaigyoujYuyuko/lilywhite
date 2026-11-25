"""HTTP 响应内容、状态码、特殊响应头、流式响应和 SSE 测试。"""

from collections.abc import AsyncIterator

import msgspec
import pytest
from litestar import Litestar, get
from litestar.background_tasks import BackgroundTask
from litestar.response import Stream
from litestar.response.sse import ServerSentEvent
from litestar.testing import TestClient

from lilywhite.http.result import created, ok, response, sse, stream, unauthorized


class CustomResult(msgspec.Struct, frozen=True):
    """业务自己定义的响应模型。"""

    code: int
    message: str


def test_ok_builds_json_object_from_keyword_fields() -> None:
    """关键字字段应直接成为响应对象，不再添加统一信封。"""
    result = ok(message="春天来了", count=1)

    assert result.status_code == 200
    assert result.content == {"message": "春天来了", "count": 1}
    assert result.headers["Cache-Control"] == "no-store"


def test_ok_preserves_business_response_model() -> None:
    """完整业务模型应原样交给 Litestar 序列化。"""
    content = CustomResult(code=0, message="ok")

    result = ok(content)

    assert result.content is content


def test_ok_rejects_mixing_model_and_keyword_fields() -> None:
    """两种内容来源混用时应明确失败，不能覆盖业务数据。"""
    with pytest.raises(ValueError, match="不能同时传入"):
        ok(CustomResult(code=0, message="ok"), message="duplicate")


def test_created_and_unauthorized_keep_status_and_special_headers() -> None:
    """便捷函数只补充 HTTP 语义，不改写业务响应模型。"""
    created_result = created(id=1, headers={"Location": "/stickers/1"})
    unauthorized_result = unauthorized(message="Authentication required.")

    assert created_result.status_code == 201
    assert created_result.content == {"id": 1}
    assert created_result.headers["Location"] == "/stickers/1"
    assert unauthorized_result.status_code == 401
    assert unauthorized_result.content == {"message": "Authentication required."}
    assert unauthorized_result.headers["WWW-Authenticate"] == "Bearer"


def test_response_forwards_litestar_options() -> None:
    """通用响应应保留 Litestar 的序列化、Cookie 和生命周期选项。"""
    background = BackgroundTask(lambda: None)
    encoders = {CustomResult: lambda result: result.message}

    result = response(
        CustomResult(code=0, message="ok"),
        background=background,
        cookies={"spring": "coming"},
        encoding="utf-16",
        type_encoders=encoders,
    )

    assert result.background is background
    assert result.cookies[0].key == "spring"
    assert result.cookies[0].value == "coming"
    assert result.encoding == "utf-16"
    assert result.response_type_encoders == encoders


def test_stream_sends_async_chunks_as_plain_http_body() -> None:
    """普通流式响应应发送内容块，并透传 Cookie 和后台任务。"""
    completed: list[str] = []

    def complete() -> None:
        completed.append("done")

    async def chunks() -> AsyncIterator[str]:
        yield "春天"
        yield "来了"

    @get("/chunks")
    async def chunk_endpoint() -> Stream:
        return stream(
            chunks(),
            status=206,
            headers={"X-Content-Mode": "chunks"},
            cookies={"spring": "coming"},
            background=BackgroundTask(complete),
        )

    with TestClient(Litestar(route_handlers=[chunk_endpoint])) as client:
        result = client.get("/chunks")

    assert result.status_code == 206
    assert result.text == "春天来了"
    assert result.headers["Content-Type"].startswith("text/plain")
    assert result.headers["X-Content-Mode"] == "chunks"
    assert result.cookies["spring"] == "coming"
    assert completed == ["done"]


def test_sse_encodes_arbitrary_models_and_heartbeats() -> None:
    """通用 SSE 应支持业务模型、自定义事件名、ID 和空事件心跳。"""
    completed: list[str] = []

    def complete() -> None:
        completed.append("done")

    async def events() -> AsyncIterator[CustomResult | None]:
        yield CustomResult(code=7, message="春天来了")
        yield None

    @get("/events")
    async def event_endpoint() -> ServerSentEvent:
        return sse(
            events(),
            event_type="greeting",
            event_id=lambda event: event.code,
            status=202,
            comment_message="connected",
            cookies={"spring": "coming"},
            background=BackgroundTask(complete),
        )

    with TestClient(Litestar(route_handlers=[event_endpoint])) as client:
        result = client.get("/events")

    assert result.status_code == 202
    assert result.cookies["spring"] == "coming"
    assert ": connected" in result.text
    assert "event: greeting" in result.text
    assert "id: 7" in result.text
    assert '"message":"春天来了"' in result.text
    assert "keep-alive" in result.text
    assert completed == ["done"]


def test_sse_accepts_fixed_event_id_and_optional_event_metadata() -> None:
    """固定事件 ID 应与回调形式一致，事件名和重试时间可以关闭。"""

    async def events() -> AsyncIterator[CustomResult | None]:
        yield CustomResult(code=7, message="春天来了")

    @get("/fixed-events")
    async def event_endpoint() -> ServerSentEvent:
        return sse(events(), event_type=None, event_id="fixed", retry_duration=None)

    with TestClient(Litestar(route_handlers=[event_endpoint])) as client:
        result = client.get("/fixed-events")

    assert result.status_code == 200
    assert "id: fixed" in result.text
    assert "event:" not in result.text
    assert "retry:" not in result.text
