"""应用组件生命周期 hook 管理。"""

import contextlib
from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Literal

from ..logger import LoggerManager
from ..utils.registry import Registry

type LifespanType = Literal["START", "STOP"]
type LifespanHook = Callable[[], Awaitable[None] | None]

log = LoggerManager.get_logger("APP")


class LifespanManager:
    """按注册顺序启动、逆序关闭并处理部分失败。"""

    def __init__(self) -> None:
        """创建空的生命周期注册表。"""
        self._start_hooks: Registry[LifespanHook] = Registry()
        self._stop_hooks: Registry[LifespanHook] = Registry()
        self._start_order: list[str] = []
        self._stop_order: list[str] = []
        self._started: list[str] = []
        self._running = False

    def register(
        self,
        name: str | None = None,
        hook_type: LifespanType = "START",
    ) -> Callable[[LifespanHook], LifespanHook]:
        """注册启动或关闭 hook，并保留原始函数。"""

        def decorator(func: LifespanHook) -> LifespanHook:
            """把函数加入指定生命周期阶段。"""
            if self._running:
                raise RuntimeError("服务运行期间不能注册生命周期 hook")
            hook_name = name or func.__name__
            key = f"{hook_type}.{hook_name}"
            hooks = self._start_hooks if hook_type == "START" else self._stop_hooks
            if hooks.get(key) is not None:
                raise ValueError(f"重复的生命周期 hook：{key}")
            hooks.register(hook_type, hook_name, func)
            if hook_type == "START":
                self._start_order.append(hook_name)
            else:
                self._stop_order.append(hook_name)
            return func

        return decorator

    async def start(self) -> None:
        """正序启动组件，失败时逆序回滚已启动组件。"""
        if self._running:
            raise RuntimeError("生命周期已经处于运行状态")
        self._running = True
        try:
            for name in self._start_order:
                log.debug("lifespan start hook name={}", name)
                await self._invoke(self._start_hooks[f"START.{name}"])
                self._started.append(name)
        except Exception:
            with contextlib.suppress(Exception):
                await self.stop()
            raise
        self._started.extend(name for name in self._stop_order if name not in self._start_order)

    async def stop(self) -> None:
        """逆序关闭组件，记录全部关闭错误后继续清理。"""
        if not self._running:
            return
        first_error: Exception | None = None
        for name in reversed(self._started):
            hook = self._stop_hooks.get(f"STOP.{name}")
            if hook is None:
                continue
            log.debug("lifespan stop hook name={}", name)
            try:
                await self._invoke(hook)
            except Exception as error:  # noqa: BLE001
                log.error("lifespan stop hook failed name={} type={}", name, type(error).__name__)  # noqa: TRY400
                if first_error is None:
                    first_error = error
        self._started.clear()
        self._running = False
        if first_error is not None:
            raise first_error

    async def __aenter__(self) -> LifespanManager:
        """启动全部已注册组件。"""
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        """关闭全部已启动组件，不抑制业务异常。"""
        await self.stop()
        return False

    @staticmethod
    async def _invoke(func: LifespanHook) -> None:
        """调用同步或异步生命周期 hook。"""
        result = func()
        if result is not None:
            await result
