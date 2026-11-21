"""不依赖代理的事务方法装饰器。"""

from collections.abc import Callable, Coroutine
from inspect import iscoroutinefunction
from typing import Any, Concatenate, Protocol

from ..transaction import TransactionBoundary


class TransactionalService(Protocol):
    """事务方法所属对象显式提供当前作用域的事务上下文。"""

    @property
    def unit_of_work(self) -> TransactionBoundary:
        """读取当前 Service 的事务边界。"""
        ...


def transactional[T: TransactionalService, **P, R](
    method: Callable[Concatenate[T, P], Coroutine[Any, Any, R]],
) -> Callable[Concatenate[T, P], Coroutine[Any, Any, R]]:
    """在 Service 的异步方法外层复用 UnitOfWork 提交或回滚。"""
    if not iscoroutinefunction(method):
        raise TypeError("@transactional 只支持 async 方法")

    async def execute(self: T, /, *args: P.args, **kwargs: P.kwargs) -> R:
        async with self.unit_of_work:
            result = await method(self, *args, **kwargs)
        return result  # noqa: RET504

    execute.__name__ = method.__name__
    execute.__qualname__ = method.__qualname__
    execute.__module__ = method.__module__
    execute.__doc__ = method.__doc__
    return execute


__all__ = ["TransactionalService", "transactional"]
