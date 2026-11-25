"""响应结束后执行的后台任务声明与注册。"""

from collections.abc import Callable
from inspect import isfunction

from ..utils.registry import Registry
from .registry import qualified_name

background_task_registry: Registry[Callable[..., object]] = Registry()


def background_task[**P, R](target: Callable[P, R]) -> Callable[P, R]:
    """声明一个可由 BackgroundManager 执行的普通同步或异步函数。"""
    if not isfunction(target):
        raise TypeError("@background_task 只能装饰普通函数")
    background_task_registry.register("background_task", qualified_name(target), target)
    return target


def is_background_task[**P, R](target: Callable[P, R]) -> bool:
    """检查调用处传入的函数是否就是已声明的任务，而非同名函数。"""
    return background_task_registry.get(f"background_task.{qualified_name(target)}") is target


__all__ = ["background_task", "background_task_registry", "is_background_task"]
