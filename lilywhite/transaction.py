"""Service 事务边界：成功提交、异常回滚，连接由依赖作用域关闭。"""

from types import TracebackType
from typing import Protocol


class TransactionSession(Protocol):
    """SQLAlchemy AsyncSession 等事务资源需要具备的最小操作。"""

    async def commit(self) -> None:
        """提交当前事务。"""
        ...

    async def rollback(self) -> None:
        """回滚当前事务。"""
        ...


class TransactionBoundary(Protocol):
    """事务装饰器只需要异步上下文，不关心 Session 的具体类型。"""

    async def __aenter__(self) -> TransactionBoundary:
        """进入事务上下文。"""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        """提交或回滚，并保留业务异常。"""
        ...


class UnitOfWork[T: TransactionSession]:
    """把一次业务用例的提交和回滚集中在一个异步上下文中。"""

    def __init__(self, session: T) -> None:
        self._session = session

    @property
    def session(self) -> T:
        """返回当前工作单元使用的 Session，供适配器显式组合。"""
        return self._session

    async def __aenter__(self) -> UnitOfWork[T]:
        """进入业务事务；事务资源由调用方的依赖作用域持有。"""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> bool:
        """无异常时提交，业务异常或提交失败时回滚；Session 由依赖作用域关闭。"""
        if exc_type is not None:
            await self._session.rollback()
            return False
        try:
            await self._session.commit()
        except BaseException:
            await self._session.rollback()
            raise
        return False


__all__ = ["TransactionBoundary", "TransactionSession", "UnitOfWork"]
