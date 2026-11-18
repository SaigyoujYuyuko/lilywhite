"""进程主线程与其他线程的未捕获异常日志钩子。"""

import sys
import threading
from collections.abc import Callable
from types import TracebackType

from ..logger import LoggerManager

log = LoggerManager.get_logger("APP")

type SysExceptionHook = Callable[[type[BaseException], BaseException, TracebackType | None], None]
type ThreadExceptionHook = Callable[[threading.ExceptHookArgs], object]


class _PreviousExceptionHooks:
    """保存安装前钩子，避免重复安装和丢失正常退出行为。"""

    def __init__(self) -> None:
        """创建空的钩子状态。"""
        self.sys: SysExceptionHook | None = None
        self.thread: ThreadExceptionHook | None = None


_previous_hooks = _PreviousExceptionHooks()


def _handle_sys_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    traceback: TracebackType | None,
) -> None:
    """记录主线程未捕获异常，正常退出仍交给原钩子。"""
    if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        previous = _previous_hooks.sys or sys.__excepthook__
        previous(exc_type, exc_value, traceback)
        return
    log.opt(exception=(exc_type, exc_value, traceback)).critical(
        "unhandled exception; process is terminating"
    )


def _handle_thread_exception(args: threading.ExceptHookArgs) -> None:
    """记录其他线程的未捕获异常，保留正常退出语义。"""
    if issubclass(args.exc_type, (KeyboardInterrupt, SystemExit)):
        previous = _previous_hooks.thread or threading.__excepthook__
        previous(args)
        return
    thread_name = args.thread.name if args.thread is not None else "unknown"
    log.opt(exception=(args.exc_type, args.exc_value, args.exc_traceback)).critical(
        "unhandled exception in thread; thread is terminating name={}",
        thread_name,
    )


def install_exception_hooks() -> None:
    """幂等安装进程和线程异常钩子，保留正常退出时的原钩子。"""
    if sys.excepthook is not _handle_sys_exception:
        _previous_hooks.sys = sys.excepthook
        sys.excepthook = _handle_sys_exception
    if threading.excepthook is not _handle_thread_exception:
        _previous_hooks.thread = threading.excepthook
        threading.excepthook = _handle_thread_exception


__all__ = ["install_exception_hooks"]
