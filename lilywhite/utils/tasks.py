"""持有并回收 fire-and-forget 异步任务的生命周期管理器。"""

import asyncio
from collections.abc import Coroutine

import msgspec

from ..decorators.component import component
from ..logger import LoggerManager

log = LoggerManager.get_logger("TASK")


class AsyncTaskSnapshot(msgspec.Struct, frozen=True):
    """后台任务管理器的单调计数与当前状态。"""

    active_tasks: int
    spawned_tasks: int
    finished_tasks: int
    failed_tasks: int


@component
class AsyncTaskManager:
    """持有任务强引用、取回异常，并在关闭时取消和等待全部任务。"""

    def __init__(self) -> None:
        """创建空任务集；组件启动前和关闭后均拒绝新任务。"""
        self._tasks: set[asyncio.Task[object]] = set()
        self._accepting = False
        self._spawned_tasks = 0
        self._finished_tasks = 0
        self._failed_tasks = 0

    async def initialize(self) -> None:
        """允许当前事件循环提交任务，重复调用安全。"""
        self._accepting = True

    def spawn[T](
        self,
        coroutine: Coroutine[object, object, T],
        *,
        name: str | None = None,
    ) -> asyncio.Task[T]:
        """创建并持有任务；关闭状态下拒绝提交并关闭传入协程。"""
        if not self._accepting:
            coroutine.close()
            raise RuntimeError("AsyncTaskManager is not accepting tasks")
        task = asyncio.create_task(coroutine, name=name)
        self._tasks.add(task)
        self._spawned_tasks += 1
        task.add_done_callback(self._finished)
        log.trace("background task spawned name={} active={}", task.get_name(), len(self._tasks))
        return task

    async def drain(self) -> None:
        """等待当前及由它们继续提交的任务结束，不主动取消。"""
        while self._tasks:
            tasks = tuple(self._tasks)
            await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self) -> None:
        """停止接收新任务，取消并等待所有未完成任务完成清理。"""
        self._accepting = False
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.drain()

    def snapshot(self) -> AsyncTaskSnapshot:
        """返回任务计数快照，不遍历或保存协程参数。"""
        return AsyncTaskSnapshot(
            active_tasks=len(self._tasks),
            spawned_tasks=self._spawned_tasks,
            finished_tasks=self._finished_tasks,
            failed_tasks=self._failed_tasks,
        )

    def _finished(self, task: asyncio.Task[object]) -> None:
        """释放强引用并取回异常，避免未观察任务异常警告。"""
        self._tasks.discard(task)
        self._finished_tasks += 1
        if task.cancelled():
            log.trace("background task cancelled name={}", task.get_name())
            return
        exception = task.exception()
        if exception is not None:
            self._failed_tasks += 1
            log.error("background task failed name={} type={}", task.get_name(), type(exception).__name__)
        else:
            log.trace("background task finished name={} active={}", task.get_name(), len(self._tasks))


__all__ = ["AsyncTaskManager", "AsyncTaskSnapshot"]
