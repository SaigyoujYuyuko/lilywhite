"""HTTP 响应内容、状态码、特殊响应头和 SSE 测试。"""

from collections.abc import AsyncIterator

import msgspec
import pytest
from litestar import Litestar, get
from litestar.response.sse import ServerSentEvent
from litestar.testing import TestClient

from lilywhite.controller.result import created, ok, sse, unauthorized


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


def test_sse_encodes_arbitrary_models_and_heartbeats() -> None:
    """通用 SSE 应支持业务模型、自定义事件名、ID 和空事件心跳。"""

    async def events() -> AsyncIterator[CustomResult | None]:
        yield CustomResult(code=7, message="春天来了")
        yield None

    @get("/events")
    async def event_endpoint() -> ServerSentEvent:
        return sse(events(), event_type="greeting", event_id=lambda event: event.code)

    with TestClient(Litestar(route_handlers=[event_endpoint])) as client:
        response = client.get("/events")

    assert response.status_code == 200
    assert "event: greeting" in response.text
    assert "id: 7" in response.text
    assert '"message":"春天来了"' in response.text
    assert "keep-alive" in response.text
