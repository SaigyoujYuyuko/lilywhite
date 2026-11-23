"""Bean 生命周期、第三方关闭适配和失败回滚测试。"""

import asyncio

import pytest

from lilywhite import AppProperties, bean, configuration, service
from lilywhite.app.container import DependencyContainer, DependencyInjectionException
from lilywhite.app.lifespan import LifespanManager
from lilywhite.app.runtime import ApplicationRuntime
from lilywhite.decorators.configuration import BeanRegistration, registered_beans
from lilywhite.utils.registry import LifetimeType


class FakeEngine:
    """模拟 SQLAlchemy AsyncEngine 的 dispose。"""

    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


class FakeRedis:
    """模拟新版 Redis 客户端的 aclose。"""

    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class FakeHttpClient:
    """模拟 httpx.AsyncClient，并验证对象自身 initialize 不会丢失。"""

    def __init__(self) -> None:
        self.initialized = False
        self.closed = False

    async def initialize(self) -> None:
        self.initialized = True

    async def aclose(self) -> None:
        self.closed = True


@configuration
class ThirdPartyClients:
    """三个常见第三方客户端共用显式关闭适配器。"""

    @bean(name="database", close=FakeEngine.dispose)
    def engine(self) -> FakeEngine:
        return FakeEngine()

    @bean(name="cache", close=FakeRedis.aclose)
    def redis(self) -> FakeRedis:
        return FakeRedis()

    @bean(name="http", close=FakeHttpClient.aclose)
    def http(self) -> FakeHttpClient:
        return FakeHttpClient()


def register_configuration(container: DependencyContainer, instance: object) -> None:
    """按公开元数据完整注册测试配置类。"""
    registrations: tuple[BeanRegistration, ...] = tuple(registered_beans(type(instance)))
    for registration in registrations:
        container.register_bean(
            instance,
            registration.factory,
            name=registration.qualifier,
            lifetime=registration.lifetime,
            close=registration.closer,
        )


def test_third_party_close_adapters_follow_application_lifecycle() -> None:
    """dispose 和 aclose 应接入统一关闭流程，initialize 仍被保留。"""

    async def exercise() -> None:
        container = DependencyContainer()
        register_configuration(container, ThirdPartyClients())
        container.build()
        managed = tuple(container.managed_component_registrations())

        assert [name for name, _component in managed] == [
            "fake_engine_database",
            "fake_http_client_http",
            "fake_redis_cache",
        ]
        for _name, component in managed:
            await component.initialize()
        for _name, component in reversed(managed):
            await component.close()

        engine = container.resolve(FakeEngine, "database")
        redis = container.resolve(FakeRedis, "cache")
        http = container.resolve(FakeHttpClient, "http")
        assert engine.disposed and redis.closed and http.closed
        assert http.initialized

    asyncio.run(exercise())


def test_scoped_and_transient_beans_are_released_by_scope() -> None:
    """Scoped 按请求复用，Transient 每次新建，二者都由作用域逆序释放。"""

    class Client:
        instances = 0

        def __init__(self) -> None:
            type(self).instances += 1
            self.close_count = 0

        async def aclose(self) -> None:
            self.close_count += 1

    @configuration
    class Clients:
        @bean(name="scoped_client", lifetime=LifetimeType.SCOPED, close=Client.aclose)
        def scoped_client(self) -> Client:
            return Client()

        @bean(name="transient_client", lifetime=LifetimeType.TRANSIENT, close=Client.aclose)
        def transient_client(self) -> Client:
            return Client()

    async def exercise() -> None:
        container = DependencyContainer()
        register_configuration(container, Clients())
        container.build()
        assert Client.instances == 0

        scope = container.create_scope()
        scoped = scope.resolve(Client, "scoped_client")
        first_transient = scope.resolve(Client, "transient_client")
        second_transient = scope.resolve(Client, "transient_client")
        assert scope.resolve(Client, "scoped_client") is scoped
        assert first_transient is not second_transient

        await scope.close()
        await scope.close()
        assert scoped.close_count == 1
        assert first_transient.close_count == 1
        assert second_transient.close_count == 1

    asyncio.run(exercise())


def test_singleton_cannot_capture_scoped_bean() -> None:
    """Bean 生命周期提升后仍应执行既有生命周期约束。"""

    class RequestClient:
        pass

    @configuration
    class Clients:
        @bean(lifetime=LifetimeType.SCOPED)
        def client(self) -> RequestClient:
            return RequestClient()

    @service
    class InvalidService:
        def __init__(self, client: RequestClient) -> None:
            self.client = client

    container = DependencyContainer()
    register_configuration(container, Clients())
    container.register_service(InvalidService)

    with pytest.raises(DependencyInjectionException, match="Singleton 不能捕获 scoped"):
        container.build()


def test_failed_initialization_closes_current_and_previous_components() -> None:
    """启动中途失败应关闭失败组件，再逆序回滚已经启动的组件。"""

    events: list[str] = []

    class FirstResource:
        async def initialize(self) -> None:
            events.append("first start")

        async def close(self) -> None:
            events.append("first close")

    class SecondResource:
        async def initialize(self) -> None:
            events.append("second start")
            raise RuntimeError("startup failed")

        async def close(self) -> None:
            events.append("second close")

    async def exercise() -> None:
        runtime = ApplicationRuntime(
            AppProperties(),
            resources={FirstResource: FirstResource(), SecondResource: SecondResource()},
        )
        with pytest.raises(RuntimeError, match="startup failed"):
            await runtime.lifespan.start()

    asyncio.run(exercise())
    assert events == ["first start", "second start", "second close", "first close"]


def test_lifespan_collects_multiple_close_errors() -> None:
    """多个关闭 hook 同时失败时应全部执行，并保留全部异常。"""

    async def exercise() -> None:
        manager = LifespanManager()

        async def fail_first() -> None:
            raise ValueError("first close")

        async def fail_second() -> None:
            raise RuntimeError("second close")

        manager.register("first", "STOP")(fail_first)
        manager.register("second", "STOP")(fail_second)
        await manager.start()
        with pytest.raises(ExceptionGroup) as captured:
            await manager.stop()
        assert [str(error) for error in captured.value.exceptions] == ["second close", "first close"]

    asyncio.run(exercise())


def test_async_scoped_bean_uses_async_scope_resolution_and_closes() -> None:
    """异步 Scoped 工厂应复用当前 Scope，并在结束时正常释放资源。"""

    class AsyncSession:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    @configuration
    class AsyncSessions:
        @bean(lifetime=LifetimeType.SCOPED)
        async def session(self) -> AsyncSession:
            return AsyncSession()

    async def exercise() -> None:
        container = DependencyContainer()
        instance = AsyncSessions()
        container.register_bean(instance, instance.session, lifetime=LifetimeType.SCOPED)
        container.build()
        scope = container.create_scope()

        first = await scope.resolve_async(AsyncSession)
        second = await scope.resolve_async(AsyncSession)
        assert first is second
        assert not first.closed
        await scope.close()
        assert first.closed

    asyncio.run(exercise())
