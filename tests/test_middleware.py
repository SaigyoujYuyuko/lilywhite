"""声明式 ASGI 中间件发现、排序、DI 和签名校验测试。"""

from importlib import import_module
from pathlib import Path

import pytest
from litestar.testing import TestClient
from litestar.types import ASGIApp, Receive, Scope, Send

from lilywhite import AppProperties, LilyWhiteApplication, middleware
from lilywhite.app.DI.container import DependencyInjectionException


def test_middleware_order_and_singleton_di_complete_real_http(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """小 order 先执行，响应按相反顺序返回，依赖来自 Singleton 容器。"""
    package = "middleware_http_app"
    root = tmp_path / package
    root.mkdir()
    (root / "__init__.py").write_text('"""中间件 HTTP 示例。"""\n', encoding="utf-8")
    (root / "tracing.py").write_text(
        "from lilywhite import service\n"
        "@service\n"
        "class TraceService:\n"
        "    def __init__(self) -> None:\n"
        "        self.events = []\n"
        "    def record(self, event: str) -> None:\n"
        '        self.events.append(f"{event}:DI")\n',
        encoding="utf-8",
    )
    (root / "middlewares.py").write_text(
        "from litestar.types import ASGIApp, Receive, Scope, Send\n"
        "from lilywhite import middleware\n"
        "from .tracing import TraceService\n"
        "@middleware(order=200)\n"
        "class LaterMiddleware:\n"
        "    def __init__(self, app: ASGIApp, trace: TraceService) -> None:\n"
        "        self.app = app\n"
        "        self.trace = trace\n"
        "    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:\n"
        '        self.trace.record("200 before")\n'
        "        await self.app(scope, receive, send)\n"
        '        self.trace.record("200 after")\n'
        "@middleware(order=100)\n"
        "class EarlierMiddleware:\n"
        "    def __init__(self, app: ASGIApp, trace: TraceService) -> None:\n"
        "        self.app = app\n"
        "        self.trace = trace\n"
        "    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:\n"
        '        self.trace.record("100 before")\n'
        "        await self.app(scope, receive, send)\n"
        '        self.trace.record("100 after")\n',
        encoding="utf-8",
    )
    (root / "routes.py").write_text(
        "from litestar import Controller, get\n"
        "from litestar.di import NamedDependency\n"
        "from lilywhite import controller\n"
        "from .tracing import TraceService\n"
        '@controller("/trace")\n'
        "class TraceController(Controller):\n"
        "    @get()\n"
        "    async def trace(self, trace_service: NamedDependency[TraceService]) -> dict[str, list[str]]:\n"
        '        trace_service.record("route")\n'
        '        return {"events": trace_service.events}\n',
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    framework = LilyWhiteApplication(
        AppProperties(),
        business_package=package,
        controller_packages=(),
    )
    application = framework.create_app()

    with TestClient(application) as client:
        response = client.get("/trace")

    tracing = import_module(f"{package}.tracing")
    trace = framework.container.resolve(tracing.TraceService)
    assert response.status_code == 200
    assert trace.events == [
        "100 before:DI",
        "200 before:DI",
        "route:DI",
        "200 after:DI",
        "100 after:DI",
    ]


def test_middleware_rejects_synchronous_call() -> None:
    """ASGI 中间件必须异步调用下一层应用。"""
    with pytest.raises(TypeError, match="async __call__"):

        @middleware
        class InvalidMiddleware:
            def __init__(self, app: ASGIApp) -> None:
                self.app = app

            def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
                return None


def test_middleware_requires_next_app_constructor_argument() -> None:
    """缺少下一层 app 时在装饰阶段失败。"""
    with pytest.raises(TypeError, match="必须接收下一层 app"):

        @middleware
        class InvalidMiddleware:
            async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
                return None


def test_middleware_rejects_scoped_dependencies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """应用级中间件不能捕获请求级 Scoped 实例。"""
    package = "invalid_middleware_scope_app"
    root = tmp_path / package
    root.mkdir()
    (root / "__init__.py").write_text('"""中间件生命周期示例。"""\n', encoding="utf-8")
    (root / "middlewares.py").write_text(
        "from litestar.types import ASGIApp, Receive, Scope, Send\n"
        "from lilywhite import middleware, service\n"
        "from lilywhite.utils.registry import LifetimeType\n"
        "@service(lifetime=LifetimeType.SCOPED)\n"
        "class RequestState:\n"
        "    pass\n"
        "@middleware\n"
        "class InvalidMiddleware:\n"
        "    def __init__(self, app: ASGIApp, state: RequestState) -> None:\n"
        "        self.app = app\n"
        "        self.state = state\n"
        "    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:\n"
        "        await self.app(scope, receive, send)\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(DependencyInjectionException, match="非 Singleton"):
        LilyWhiteApplication(AppProperties(), business_package=package, controller_packages=()).create_app()
