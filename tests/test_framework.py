"""LilyWhite 公开接口、示例应用与启动 Banner 的行为测试。"""

import pytest
from litestar.testing import TestClient

import lilywhite.app.main as main_module
from lilywhite import LilyWhiteApplication, LilywhiteMain, run
from lilywhite.banner import render_banner
from lilywhite.config import AppProperties


def test_greeting_uses_complete_dependency_injection_chain() -> None:
    """示例请求必须经过 Controller、Service 和内存 Repository。"""
    application = LilyWhiteApplication(
        AppProperties(),
        business_package="example",
        application_name="LilyWhite Test",
    ).create_app()

    with TestClient(application) as client:
        response = client.get("/api/v1/greetings/Lily")

    assert response.status_code == 200
    assert response.json()["body"]["message"] == "你好，Lily！lilywhite 模板已经运行。"


def test_main_marks_entry_and_injects_asgi_call() -> None:
    """入口装饰器必须保留类型并让实例成为 ASGI 可调用对象。"""

    @LilywhiteMain
    class DemoApplication:
        pass

    assert getattr(DemoApplication, "__lilywhite_main__", False) is True
    assert callable(DemoApplication())


def test_run_rejects_unmarked_entry_before_reading_configuration() -> None:
    """未标记入口必须在读取配置或启动服务前失败。"""

    class UnmarkedApplication:
        pass

    with pytest.raises(TypeError, match="LilywhiteMain"):
        run(UnmarkedApplication, [])


def test_banner_contains_application_metadata_and_server_url() -> None:
    """Banner 必须展示应用名称、版本和实际配置的启动 URL。"""
    banner = render_banner("LilyWhite Test", "1.2.3", "127.0.0.1", 9527)

    assert "LilyWhite Test v1.2.3" in banner
    assert "http://127.0.0.1:9527" in banner
    assert "Bringing Spring to Python." in banner


def test_websocket_controller_receives_and_returns_messages() -> None:
    """WebSocket Controller 必须随业务包发现并完成真实消息收发。"""
    application = LilyWhiteApplication(
        AppProperties(),
        business_package="example",
        application_name="LilyWhite WebSocket Test",
    ).create_app()

    with TestClient(application) as client, client.websocket_connect("/ws/echo") as websocket:
        websocket.send_text("春天来了")
        response = websocket.receive_text()

    assert response == "LilyWhite 回声：春天来了"


def test_custom_entry_banner_replaces_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """入口类 banner() 的字符串应取代框架默认 Banner。"""

    @LilywhiteMain
    class CustomBannerApplication:
        def banner(self) -> str:
            return "CUSTOM SPRING BANNER"

    monkeypatch.setattr(main_module, "_create_application", lambda *args, **kwargs: object())
    monkeypatch.setattr(main_module.uvicorn, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module, "shutdown_logging", lambda: None)

    run(CustomBannerApplication, ["--config", "config.example.yaml"])

    captured = capsys.readouterr()
    assert "CUSTOM SPRING BANNER" in captured.out
    assert "Bringing Spring to Python." not in captured.out


def test_entry_shutdown_hook_runs_after_real_lifespan() -> None:
    """入口的 STOP-only hook 必须随 Litestar lifespan 正常执行。"""
    events: list[str] = []

    @LilywhiteMain
    class LifecycleApplication:
        async def on_startup(self) -> None:
            events.append("startup")

        async def on_shutdown(self) -> None:
            events.append("shutdown")

    LifecycleApplication.__module__ = "example.application"
    entry = LifecycleApplication()
    application = main_module._create_application(
        LifecycleApplication,
        AppProperties(),
        ("memory",),
        entry=entry,
    )

    with TestClient(application):
        pass

    assert events == ["startup", "shutdown"]
