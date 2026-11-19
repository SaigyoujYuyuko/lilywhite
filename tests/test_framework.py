"""LilyWhite 公开接口、示例应用与启动 Banner 的行为测试。"""

import logging

import pytest
from litestar.testing import TestClient

import lilywhite.app.main as main_module
from example.application import _time_greeting
from lilywhite import LilyWhiteApplication, LilywhiteMain, override_logger, run
from lilywhite.banner import render_banner
from lilywhite.config import AppProperties
from lilywhite.logger import LoggerManager


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


@pytest.mark.parametrize(
    ("hour", "expected"),
    [
        (8, "Good Morning, have a nice day in your app!"),
        (12, "sun is on mid. have a nice launch!"),
        (15, "Good Afternoon！"),
        (20, "Good evening"),
        (1, "Good midnight！you sleep so lately，keep your body！"),
    ],
)
def test_example_banner_greeting_matches_local_time(hour: int, expected: str) -> None:
    """示例彩蛋应覆盖早上、中午、下午、晚上和跨午夜。"""
    assert _time_greeting(hour) == expected


def test_default_banner_includes_optional_entry_message(capsys: pytest.CaptureFixture[str]) -> None:
    """附加消息应保留默认字符画、版本和启动 URL。"""

    class MessageApplication:
        application_name = "Message Test"

        def banner_message(self) -> str:
            return "HAVE A NICE DAY"

    main_module._print_entry_banner(MessageApplication, AppProperties(), entry=MessageApplication())

    captured = capsys.readouterr()
    assert "Bringing Spring to Python." in captured.out
    assert "Message Test v0.1.0" in captured.out
    assert "http://127.0.0.1:8000" in captured.out
    assert "HAVE A NICE DAY" in captured.out


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


class _LogCollector(logging.Handler):
    """在内存中保留标准 logging 记录。"""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_entry_override_logger_accepts_standard_logger_instance() -> None:
    """入口声明的标准 Logger 应接管真实启动、DI 和关闭日志。"""
    custom_logger = logging.getLogger("tests.custom_entry")
    custom_logger.setLevel(logging.DEBUG)
    custom_logger.propagate = False
    collector = _LogCollector()
    custom_logger.addHandler(collector)

    @LilywhiteMain
    class CustomLoggerApplication:
        def override_logger(self) -> logging.Logger:
            return custom_logger

    CustomLoggerApplication.__module__ = "example.application"
    entry = CustomLoggerApplication()
    try:
        application = main_module._create_application(
            CustomLoggerApplication,
            AppProperties(),
            ("memory",),
            entry=entry,
        )
        with TestClient(application):
            pass
    finally:
        override_logger(None)
        custom_logger.removeHandler(collector)

    messages = [record.getMessage() for record in collector.records]
    assert "logging initialized" in messages
    assert any(
        message.startswith("dependency container scan start backends=('memory',)") for message in messages
    )
    assert "server shutdown complete" in messages


def test_override_logger_factory_updates_existing_reference_and_exception() -> None:
    """工厂应按模块取名，旧适配器也应切换并保留异常信息。"""
    custom_logger = logging.getLogger("custom.factory")
    custom_logger.setLevel(logging.DEBUG)
    custom_logger.propagate = False
    collector = _LogCollector()
    custom_logger.addHandler(collector)
    adapted = LoggerManager.get_logger("custom.factory")
    error = ValueError("bad spring")

    try:
        override_logger(logging.getLogger)
        adapted.info("hello {}", "world")
        adapted.opt(exception=(ValueError, error, None)).critical("unhandled exception")
    finally:
        override_logger(None)
        custom_logger.removeHandler(collector)

    assert [record.name for record in collector.records] == ["custom.factory", "custom.factory"]
    assert collector.records[0].getMessage() == "hello world"
    assert collector.records[1].exc_info == (ValueError, error, None)
