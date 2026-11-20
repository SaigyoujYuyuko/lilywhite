"""同类型多实例的限定注入、Litestar 桥接和生命周期测试。"""

from importlib import import_module
from pathlib import Path
from typing import Annotated

import pytest
from litestar.testing import TestClient

from lilywhite import AppProperties, LilyWhiteApplication, Qualifier, bean, configuration, repository, service
from lilywhite.app.container import DependencyContainer, DependencyInjectionException
from lilywhite.decorators.configuration import registered_beans
from lilywhite.utils.registry import LifetimeType


class Engine:
    """模拟两个数据库 Engine 共用一个 Python 类型。"""

    def __init__(self, url: str) -> None:
        self.url = url


class EnginePair:
    """同时持有主库和只读库的业务对象。"""

    def __init__(
        self,
        primary: Annotated[Engine, Qualifier("primary")],
        replica: Annotated[Engine, Qualifier("replica")],
    ) -> None:
        self.primary = primary
        self.replica = replica


@configuration
class DatabaseClients:
    """同类型 Bean 用名称共存，工厂参数用 Qualifier 选择。"""

    @bean(name="primary")
    def primary_engine(self) -> Engine:
        return Engine("postgresql://primary")

    @bean(name="replica")
    def replica_engine(self) -> Engine:
        return Engine("postgresql://replica")

    @bean
    def pair(
        self,
        primary: Annotated[Engine, Qualifier("primary")],
        replica: Annotated[Engine, Qualifier("replica")],
    ) -> EnginePair:
        return EnginePair(primary, replica)


def test_named_beans_support_multiple_databases_and_require_qualifier() -> None:
    """两个 Engine 应独立构造、按名注入，未命名解析应报告冲突。"""
    container = DependencyContainer()
    clients = DatabaseClients()
    for registration in registered_beans(DatabaseClients):
        container.register_bean(
            clients,
            registration.factory,
            name=registration.qualifier,
            lifetime=registration.lifetime,
            close=registration.closer,
        )
    container.build()

    pair = container.resolve(EnginePair)

    assert pair.primary.url == "postgresql://primary"
    assert pair.replica.url == "postgresql://replica"
    assert container.resolve(Engine, "primary") is pair.primary
    assert container.resolve(Engine, "replica") is pair.replica
    with pytest.raises(DependencyInjectionException, match="Qualifier"):
        container.resolve(Engine)


def test_named_repositories_coexist_and_service_selects_one() -> None:
    """同一 Interface 的多个启用实现应通过注入点的限定名选择。"""

    class GreetingRepository:
        def greeting(self) -> str:
            raise NotImplementedError

    @repository(GreetingRepository, name="memory")
    class MemoryRepository(GreetingRepository):
        def greeting(self) -> str:
            return "memory"

    @repository(GreetingRepository, name="persistent")
    class PersistentRepository(GreetingRepository):
        def greeting(self) -> str:
            return "persistent"

    @service
    class GreetingService:
        def __init__(self, repository: Annotated[GreetingRepository, Qualifier("persistent")]) -> None:
            self.repository = repository

    container = DependencyContainer(package_names=(__name__,))
    container.register_service(GreetingService)
    container.build()

    assert container.resolve(GreetingService).repository.greeting() == "persistent"
    assert container.resolve(GreetingRepository, "memory").greeting() == "memory"
    with pytest.raises(DependencyInjectionException, match="多个实现"):
        container.resolve(GreetingRepository)


def test_scoped_cache_separates_qualifiers_and_request_scopes() -> None:
    """同请求内按名称复用 Scoped，不同名称和不同请求之间不得串实例。"""

    class Cache:
        pass

    class MemoryCache(Cache):
        pass

    class RedisCache(Cache):
        pass

    container = DependencyContainer()
    container.register_component(Cache, MemoryCache, LifetimeType.SCOPED, name="memory")
    container.register_component(Cache, RedisCache, LifetimeType.SCOPED, name="redis")
    first_scope = container.create_scope()
    second_scope = container.create_scope()

    memory = first_scope.resolve(Cache, "memory")
    redis = first_scope.resolve(Cache, "redis")

    assert first_scope.resolve(Cache, "memory") is memory
    assert first_scope.resolve(Cache, "redis") is redis
    assert memory is not redis
    assert second_scope.resolve(Cache, "memory") is not memory
    with pytest.raises(DependencyInjectionException, match="多个实现"):
        first_scope.resolve(Cache)


def test_dependency_rejects_multiple_qualifiers() -> None:
    """一个参数同时声明两个限定名应在图校验阶段直接失败。"""

    class InvalidService:
        def __init__(
            self,
            engine: Annotated[Engine, Qualifier("primary"), Qualifier("replica")],
        ) -> None:
            self.engine = engine

    container = DependencyContainer()
    container.register_service(InvalidService)

    with pytest.raises(DependencyInjectionException, match="只能声明一个 Qualifier"):
        container.build()


@pytest.mark.parametrize("name", ["", " primary ", "   "])
def test_qualifier_rejects_empty_and_padded_names(name: str) -> None:
    """限定名应尽早拒绝空字符串和容易误写的首尾空白。"""
    with pytest.raises(ValueError, match="必须非空"):
        Qualifier(name)


def test_named_clients_complete_real_http_and_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """命名 Bean 应经过 AST、容器和 Litestar，并分别启动和关闭。"""
    package = "qualified_http_app"
    root = tmp_path / package
    root.mkdir()
    (root / "__init__.py").write_text('"""命名客户端 HTTP 示例。"""\n', encoding="utf-8")
    (root / "clients.py").write_text(
        "from lilywhite import bean, configuration\n"
        "class HttpClient:\n"
        "    def __init__(self, base_url: str) -> None:\n"
        "        self.base_url = base_url\n"
        "        self.initialized = False\n"
        "        self.closed = False\n"
        "    async def initialize(self) -> None:\n"
        "        self.initialized = True\n"
        "    async def close(self) -> None:\n"
        "        self.closed = True\n"
        "@configuration\n"
        "class ClientConfiguration:\n"
        "    @bean(name='primary')\n"
        "    def primary(self) -> HttpClient:\n"
        "        return HttpClient('https://primary.example')\n"
        "    @bean(name='secondary')\n"
        "    def secondary(self) -> HttpClient:\n"
        "        return HttpClient('https://secondary.example')\n",
        encoding="utf-8",
    )
    (root / "web.py").write_text(
        "from typing import Annotated\n"
        "from litestar import Controller, get\n"
        "from litestar.di import NamedDependency\n"
        "from lilywhite import Qualifier, controller\n"
        "from .clients import HttpClient\n"
        "@controller('/api')\n"
        "class ClientController(Controller):\n"
        "    @get('/clients')\n"
        "    async def clients(\n"
        "        self,\n"
        "        primary: NamedDependency[Annotated[HttpClient, Qualifier('primary')]],\n"
        "        secondary: NamedDependency[Annotated[HttpClient, Qualifier('secondary')]],\n"
        "    ) -> dict[str, str]:\n"
        "        return {'primary': primary.base_url, 'secondary': secondary.base_url}\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    framework = LilyWhiteApplication(AppProperties(), business_package=package)

    with TestClient(framework.create_app()) as client:
        response = client.get("/api/clients")
        primary = framework.container.resolve(_client_type(package), "primary")
        secondary = framework.container.resolve(_client_type(package), "secondary")
        assert primary.initialized and secondary.initialized

    assert response.status_code == 200
    assert response.json() == {
        "primary": "https://primary.example",
        "secondary": "https://secondary.example",
    }
    assert primary.closed and secondary.closed


def _client_type(package: str) -> type[object]:
    """取得临时包中的客户端类型，避免把动态模块导入细节混入行为断言。"""
    client_type = import_module(f"{package}.clients").HttpClient
    assert isinstance(client_type, type)
    return client_type
