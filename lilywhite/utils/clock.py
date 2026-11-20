"""业务时间来源，避免 Domain 和 Service 直接读取系统时钟。"""

import time
from typing import Protocol

from ..decorators.component import component


class Clock(Protocol):
    """同时提供持久化 wall time 与限流使用的单调时间。"""

    def time(self) -> float:
        """返回 Unix 时间戳。"""
        ...

    def monotonic(self) -> float:
        """返回只用于耗时和窗口计算的单调时间。"""
        ...


@component(interface=Clock)
class SystemClock:
    """基于标准库的系统时钟。"""

    def time(self) -> float:
        """返回当前 Unix 时间戳。"""
        return time.time()

    def monotonic(self) -> float:
        """返回当前单调时间。"""
        return time.monotonic()


__all__ = ["Clock", "SystemClock"]
