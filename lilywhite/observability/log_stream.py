"""Loguru 日志的有界内存历史与异步订阅。"""

import asyncio
import contextlib
import threading
from collections import deque
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import loguru
import msgspec
from loguru import logger

from ..logger import third_party_log_filter

if TYPE_CHECKING:
    from loguru import Record as LoguruRecord
else:
    LoguruRecord = dict[str, object]

_HISTORY_SIZE = 200
_QUEUE_SIZE = 256
_MAX_SUBSCRIBERS = 8
_KEEP_ALIVE_SECONDS = 15


class LogEvent(msgspec.Struct, frozen=True):
    """可安全发送给运维面板的一条日志元数据。"""

    id: int
    timestamp: str
    level: str
    logger: str
    module: str
    message: str
    request_id: str


class LogSubscriptionLimitException(RuntimeError):
    """同时读取日志的订阅数量已达到上限。"""


class _StopSignal:
    """标识日志组件关闭的内部队列消息。"""


class _LogSubscriber:
    """绑定事件循环、有限队列和关闭状态的订阅者。"""

    def __init__(self, subscriber_id: int, loop: asyncio.AbstractEventLoop) -> None:
        """创建一个等待日志的订阅者。"""
        self.id = subscriber_id
        self.loop = loop
        self.queue: asyncio.Queue[LogEvent | _StopSignal] = asyncio.Queue(maxsize=_QUEUE_SIZE)
        self.closed = False


class LogSubscription:
    """单次日志订阅，取消迭代时自动释放订阅者资源。"""

    def __init__(self, stream: LogStream, subscriber: _LogSubscriber) -> None:
        """保存所属日志流和订阅者。"""
        self._stream = stream
        self._subscriber = subscriber

    async def events(self) -> AsyncIterator[LogEvent | None]:
        """产生日志事件，超时产生 None 作为传输层心跳。"""
        try:
            while not self._subscriber.closed:
                try:
                    item = await asyncio.wait_for(self._subscriber.queue.get(), _KEEP_ALIVE_SECONDS)
                except TimeoutError:
                    yield None
                    continue
                if isinstance(item, LogEvent):
                    yield item
        finally:
            self._subscriber.closed = True
            self._stream._unsubscribe(self._subscriber.id)


class LogStream:
    """在线程安全的日志入口与异步订阅者之间分发有界日志。"""

    def __init__(self, level: str, third_party_level: str) -> None:
        """设置订阅级别和第三方过滤规则，构造时不修改进程日志配置。"""
        self._level = level
        self._third_party_filter = third_party_log_filter(third_party_level)
        self._lock = threading.Lock()
        self._history: deque[LogEvent] = deque(maxlen=_HISTORY_SIZE)
        self._subscribers: dict[int, _LogSubscriber] = {}
        self._next_event_id = 1
        self._next_subscriber_id = 1
        self._sink_id: int | None = None
        self._closed = True

    async def initialize(self) -> None:
        """挂载 Loguru sink，开始接收运行期日志。"""
        with self._lock:
            if not self._closed:
                return
            self._closed = False
        self._sink_id = logger.add(
            self._write,
            level=self._level,
            enqueue=True,
            backtrace=False,
            diagnose=False,
            filter=self._third_party_filter,
        )

    async def close(self) -> None:
        """移除 sink 并唤醒全部订阅者完成退出。"""
        with self._lock:
            self._closed = True
            sink_id = self._sink_id
            self._sink_id = None
            subscribers = tuple(self._subscribers.values())
            self._subscribers.clear()
        if sink_id is not None:
            with contextlib.suppress(ValueError):
                logger.remove(sink_id)
        for subscriber in subscribers:
            with contextlib.suppress(RuntimeError):
                subscriber.loop.call_soon_threadsafe(self._stop_subscriber, subscriber)

    def subscribe(self) -> LogSubscription:
        """注册订阅者并先回放有界历史，订阅数超限时拒绝。"""
        with self._lock:
            if self._closed:
                raise RuntimeError("日志流尚未启动")
            if len(self._subscribers) >= _MAX_SUBSCRIBERS:
                raise LogSubscriptionLimitException
            subscriber = _LogSubscriber(self._next_subscriber_id, asyncio.get_running_loop())
            self._next_subscriber_id += 1
            for event in self._history:
                subscriber.queue.put_nowait(event)
            self._subscribers[subscriber.id] = subscriber
        return LogSubscription(self, subscriber)

    def _write(self, message: loguru.Message) -> None:
        """从 Loguru 消息提取记录，不序列化异常堆栈。"""
        record = message.record
        request_id = record["extra"].get("request_id", "")
        with self._lock:
            if self._closed:
                return
            event = LogEvent(
                id=self._next_event_id,
                timestamp=record["time"].isoformat(timespec="milliseconds"),
                level=record["level"].name,
                logger=record["name"] or "",
                module=str(record["extra"].get("module", "")),
                message=record["message"],
                request_id=request_id if isinstance(request_id, str) else "",
            )
            self._next_event_id += 1
            self._history.append(event)
            subscribers = tuple(self._subscribers.values())
        for subscriber in subscribers:
            with contextlib.suppress(RuntimeError):
                subscriber.loop.call_soon_threadsafe(self._deliver, subscriber, event)

    def _deliver(self, subscriber: _LogSubscriber, event: LogEvent) -> None:
        """在订阅者事件循环中投递，队列满时丢弃最旧消息。"""
        if subscriber.closed:
            return
        if subscriber.queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                subscriber.queue.get_nowait()
        subscriber.queue.put_nowait(event)

    def _stop_subscriber(self, subscriber: _LogSubscriber) -> None:
        """清空待发送日志并放置关闭信号。"""
        subscriber.closed = True
        while not subscriber.queue.empty():
            subscriber.queue.get_nowait()
        subscriber.queue.put_nowait(_StopSignal())

    def _unsubscribe(self, subscriber_id: int) -> None:
        """移除已经断开或取消的订阅者。"""
        with self._lock:
            self._subscribers.pop(subscriber_id, None)


__all__ = ["LogEvent", "LogStream", "LogSubscription", "LogSubscriptionLimitException"]
