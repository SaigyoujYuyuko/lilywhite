"""多 Repository 共享 Session 的提交、回滚和作用域清理测试。"""

import asyncio
import contextlib

import pytest

from lilywhite import UnitOfWork, bean, configuration, service, transactional
from lilywhite.app.container import DependencyContainer
from lilywhite.decorators.configuration import registered_beans
from lilywhite.utils.registry import LifetimeType


class FakeSession:
    """记录 SQLAlchemy AsyncSession 等价的事务与关闭行为。"""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.closed = False

    async def commit(self) -> None:
        self.events.append("commit")

    async def rollback(self) -> None:
        self.events.append("rollback")

    async def close(self) -> None:
        self.closed = True
        self.events.append("close")


class IdentityRepository:
    """第一个 Repository 只写 Session，不自行提交。"""

    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def save(self) -> None:
        self.session.events.append("identity write")


class BillingRepository:
    """第二个 Repository 共享同一事务，不持有全局 Session。"""

    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def save(self, *, fail: bool = False) -> None:
        self.session.events.append("billing write")
        if fail:
            raise ValueError("billing failed")


@configuration
class Persistence:
    """Session 与 UnitOfWork 都是请求级 Scoped Bean。"""

    @bean(lifetime=LifetimeType.SCOPED)
    def session(self) -> FakeSession:
        return FakeSession()

    @bean(lifetime=LifetimeType.SCOPED)
    def unit_of_work(self, session: FakeSession) -> UnitOfWork[FakeSession]:
        return UnitOfWork(session)


@service(lifetime=LifetimeType.SCOPED)
class CheckoutService:
    """Service 拥有业务事务边界，两个 Repository 参与同一事务。"""

    def __init__(
        self,
        unit_of_work: UnitOfWork[FakeSession],
        identity: IdentityRepository,
        billing: BillingRepository,
    ) -> None:
        self.unit_of_work = unit_of_work
        self.identity = identity
        self.billing = billing

    @transactional
    async def checkout(self, *, fail: bool = False) -> None:
        await self.identity.save()
        await self.billing.save(fail=fail)


def build_container() -> DependencyContainer:
    """装配 Session、UoW、两个 Repository 和事务 Service。"""
    container = DependencyContainer()
    configuration_instance = Persistence()
    for registration in registered_beans(Persistence):
        container.register_bean(
            configuration_instance,
            registration.factory,
            name=registration.qualifier,
            lifetime=registration.lifetime,
            close=registration.closer,
        )
    container.register_component(IdentityRepository, IdentityRepository, LifetimeType.SCOPED)
    container.register_component(BillingRepository, BillingRepository, LifetimeType.SCOPED)
    container.register_service(CheckoutService, LifetimeType.SCOPED)
    container.build()
    return container


def test_repositories_commit_and_release_shared_session() -> None:
    """成功用例只提交一次，两个 Repository 共享并在末尾关闭同一 Session。"""

    async def exercise() -> None:
        container = build_container()
        scope = container.create_scope()
        service_instance = scope.resolve(CheckoutService)
        session = scope.resolve(FakeSession)
        await service_instance.checkout()

        assert service_instance.identity.session is session
        assert service_instance.billing.session is session
        assert session.events == ["identity write", "billing write", "commit"]
        await scope.close()
        assert session.events[-1] == "close"
        assert session.closed

    asyncio.run(exercise())


def test_exception_rolls_back_and_still_releases_session() -> None:
    """业务异常应回滚而不是提交，异常传播后仍可显式释放连接。"""

    async def exercise() -> None:
        scope = build_container().create_scope()
        service_instance = scope.resolve(CheckoutService)
        session = scope.resolve(FakeSession)
        try:
            await service_instance.checkout(fail=True)
        except ValueError:
            pass
        finally:
            await scope.close()

        assert session.events == ["identity write", "billing write", "rollback", "close"]

    asyncio.run(exercise())


def test_background_jobs_receive_independent_transaction_scopes() -> None:
    """两个后台任务不得共享 Session 或事务状态。"""

    async def job(container: DependencyContainer, *, fail: bool) -> FakeSession:
        scope = container.create_scope()
        try:
            service_instance = scope.resolve(CheckoutService)
            session = scope.resolve(FakeSession)
            with contextlib.suppress(ValueError):
                await service_instance.checkout(fail=fail)
            return session
        finally:
            await scope.close()

    async def exercise() -> None:
        container = build_container()
        first, second = await asyncio.gather(job(container, fail=False), job(container, fail=True))
        assert first is not second
        assert first.events == ["identity write", "billing write", "commit", "close"]
        assert second.events == ["identity write", "billing write", "rollback", "close"]

    asyncio.run(exercise())


def test_commit_failure_also_rolls_back() -> None:
    """提交阶段自身失败时也应回滚，而不是留下半完成事务。"""

    class CommitFailureSession(FakeSession):
        async def commit(self) -> None:
            self.events.append("commit")
            raise RuntimeError("commit failed")

    async def exercise() -> None:
        session = CommitFailureSession()
        unit_of_work = UnitOfWork(session)
        with pytest.raises(RuntimeError, match="commit failed"):
            async with unit_of_work:
                session.events.append("write")
        assert session.events == ["write", "commit", "rollback"]

    asyncio.run(exercise())


def test_transactional_rejects_sync_methods() -> None:
    """事务装饰器不隐式创建事件循环，同步方法在声明时直接报错。"""
    with pytest.raises(TypeError, match="只支持 async"):

        @transactional
        def invalid(self: CheckoutService) -> None:
            pass


def test_nested_success_commits_only_at_outermost_boundary() -> None:
    """内层成功只退出当前边界，最外层成功时才提交一次。"""

    async def exercise() -> None:
        session = FakeSession()
        unit_of_work = UnitOfWork(session)

        async with unit_of_work:
            session.events.append("outer write")
            async with unit_of_work:
                session.events.append("inner write")
                assert "commit" not in session.events
            session.events.append("after inner")

        assert session.events == ["outer write", "inner write", "after inner", "commit"]

    asyncio.run(exercise())


def test_caught_inner_exception_still_rolls_back_entire_transaction() -> None:
    """外层捕获内层异常也不能清除回滚标记，避免提交不完整业务。"""

    async def exercise() -> None:
        session = FakeSession()
        unit_of_work = UnitOfWork(session)

        async with unit_of_work:
            session.events.append("outer write")
            with contextlib.suppress(ValueError):
                async with unit_of_work:
                    session.events.append("inner write")
                    raise ValueError("inner failed")
            session.events.append("inner failure caught")
            session.events.append("after inner")

        assert session.events == [
            "outer write",
            "inner write",
            "inner failure caught",
            "after inner",
            "rollback",
        ]

    asyncio.run(exercise())


def test_unit_of_work_can_be_reused_after_rollback() -> None:
    """最外层回滚后应清理事务状态，后续独立用例仍可正常提交。"""

    async def exercise() -> None:
        session = FakeSession()
        unit_of_work = UnitOfWork(session)

        with pytest.raises(ValueError, match="first failed"):
            async with unit_of_work:
                session.events.append("first write")
                raise ValueError("first failed")
        async with unit_of_work:
            session.events.append("second write")

        assert session.events == ["first write", "rollback", "second write", "commit"]

    asyncio.run(exercise())
