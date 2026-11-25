"""声明式响应后台任务的并发、观测与优雅关闭管理。"""

import asyncio
from collections.abc import Awaitable, Callable
from inspect import isawaitable, iscoroutinefunction

from litestar.background_tasks import BackgroundTask

from ..config import AppProperties
from ..decorators.background import is_background_task
from ..decorators.component import component
from ..decorators.registry import qualified_name
from .tasks import AsyncTaskManager, AsyncTaskSnapshot


@component
class BackgroundManager:
    """把已声明任务绑定到 Response，并复用统一异步任务生命周期。"""

    def __init__(self, tasks: AsyncTaskManager, properties: AppProperties) -> None:
        """保存共享任务管理器，并按配置建立全局并发限制。"""
        self._tasks = tasks
        max_concurrency = properties.background.max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency) if max_concurrency > 0 else None
        self._accepting = False

    async def initialize(self) -> None:
        """允许创建响应后台任务；共享管理器可重复初始化。"""
        await self._tasks.initialize()
        self._accepting = True

    def defer[**P, R](self, target: Callable[P, R], /, *args: P.args, **kwargs: P.kwargs) -> BackgroundTask:
        """把声明式任务及其显式参数封装为 Litestar BackgroundTask。"""
        if not self._accepting:
            raise RuntimeError("BackgroundManager is not accepting tasks")
        if not is_background_task(target):
            raise ValueError(f"后台任务必须使用 @background_task 声明：{qualified_name(target)}")

        async def execute() -> None:
            """在响应结束后执行任务，并由共享管理器持有强引用。"""
            await self._execute(target, *args, **kwargs)

        return BackgroundTask(execute)

    async def close(self) -> None:
        """停止接收新任务，等待已经开始的响应后台任务完成。"""
        self._accepting = False
        await self._tasks.drain()

    def snapshot(self) -> AsyncTaskSnapshot:
        """返回共享异步任务的当前计数，不保存或暴露任务参数。"""
        return self._tasks.snapshot()

    async def _execute[**P, R](self, target: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> None:
        """从排队阶段开始跟踪任务，确保关闭时也能等待并发槽位。"""
        if not self._accepting:
            raise RuntimeError("BackgroundManager is not accepting tasks")
        task = self._tasks.spawn(self._invoke(target, *args, **kwargs), name=qualified_name(target))
        await task

    async def _invoke[**P, R](self, target: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> None:
        """在信号量范围内运行任务，让全部实例共享同一并发上限。"""
        if self._semaphore is None:
            await self._call(target, *args, **kwargs)
            return
        async with self._semaphore:
            await self._call(target, *args, **kwargs)

    async def _call[**P, R](self, target: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> None:
        """异步函数直接运行，同步函数放入线程，避免阻塞事件循环。"""
        operation: Callable[P, R] | Callable[P, Awaitable[R]] = target
        if iscoroutinefunction(operation):
            result = await operation(*args, **kwargs)
        else:
            result = await asyncio.to_thread(target, *args, **kwargs)
        if isawaitable(result):
            await result


__all__ = ["BackgroundManager"]
