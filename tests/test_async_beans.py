"""异步 Bean 经 lifespan、DI、真实 HTTP 和资源关闭的集成测试。"""

from importlib import import_module
from pathlib import Path

import pytest
from litestar.testing import TestClient

from lilywhite import AppProperties, LilyWhiteApplication


def test_async_beans_complete_real_http_and_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """异步 Singleton 和 Scoped Bean 应注入 Service，并随应用和请求关闭。"""
    package = "async_bean_http_app"
    root = tmp_path / package
    root.mkdir()
    (root / "__init__.py").write_text('"""异步 Bean HTTP 示例。"""\n', encoding="utf-8")
    (root / "infra.py").write_text(
        "from lilywhite import bean, configuration\n"
        "from lilywhite.utils.registry import LifetimeType\n"
        "class Engine:\n"
        "    instances = []\n"
        "    def __init__(self) -> None:\n"
        "        self.closed = False\n"
        "        type(self).instances.append(self)\n"
        "    async def aclose(self) -> None:\n"
        "        self.closed = True\n"
        "class Session:\n"
        "    instances = []\n"
        "    def __init__(self, engine: Engine) -> None:\n"
        "        self.engine = engine\n"
        "        self.closed = False\n"
        "        type(self).instances.append(self)\n"
        "    async def close(self) -> None:\n"
        "        self.closed = True\n"
        "@configuration\n"
        "class Infrastructure:\n"
        "    @bean(close=Engine.aclose)\n"
        "    async def engine(self) -> Engine:\n"
        "        return Engine()\n"
        "    @bean(lifetime=LifetimeType.SCOPED)\n"
        "    async def session(self, engine: Engine) -> Session:\n"
        "        return Session(engine)\n",
        encoding="utf-8",
    )
    (root / "services.py").write_text(
        "from lilywhite import service\n"
        "from lilywhite.utils.registry import LifetimeType\n"
        "from .infra import Engine, Session\n"
        "@service\n"
        "class EngineService:\n"
        "    def __init__(self, engine: Engine) -> None:\n"
        "        self.engine = engine\n"
        "@service(lifetime=LifetimeType.SCOPED)\n"
        "class SessionService:\n"
        "    def __init__(self, session: Session) -> None:\n"
        "        self.session = session\n",
        encoding="utf-8",
    )
    (root / "routes.py").write_text(
        "from litestar import Controller, get\n"
        "from litestar.di import NamedDependency\n"
        "from lilywhite import controller\n"
        "from .services import EngineService, SessionService\n"
        '@controller("/async")\n'
        "class AsyncController(Controller):\n"
        '    @get("/engine")\n'
        "    async def engine(self, engine_service: NamedDependency[EngineService]) -> dict[str, bool]:\n"
        '        return {"closed": engine_service.engine.closed}\n'
        '    @get("/session")\n'
        "    async def session(self, session_service: NamedDependency[SessionService]) -> dict[str, int]:\n"
        '        return {"session": id(session_service.session)}\n',
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    application = LilyWhiteApplication(
        AppProperties(),
        business_package=package,
        controller_packages=(),
    ).create_app()

    with TestClient(application) as client:
        engine_response = client.get("/async/engine")
        first_session = client.get("/async/session")
        second_session = client.get("/async/session")

    infrastructure = import_module(f"{package}.infra")
    assert engine_response.json() == {"closed": False}
    assert first_session.json()["session"] != second_session.json()["session"]
    assert len(infrastructure.Engine.instances) == 1
    assert infrastructure.Engine.instances[0].closed
    assert len(infrastructure.Session.instances) == 2
    assert all(session.closed for session in infrastructure.Session.instances)
