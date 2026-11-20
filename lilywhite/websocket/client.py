"""用于连接外部 WebSocket 服务端的异步客户端。"""

import asyncio
from collections.abc import Mapping
from ssl import SSLContext
from types import TracebackType
from typing import overload

import msgspec
from websockets.asyncio.client import ClientConnection
from websockets.asyncio.client import connect as open_connection
from websockets.exceptions import ConnectionClosedOK
from websockets.protocol import State


class WebSocketClient:
    """持有一个出站连接，支持上下文管理和 LilyWhite 组件生命周期。"""

    def __init__(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        connect_timeout: float | None = 10,
        ping_interval: float | None = 20,
        ping_timeout: float | None = 20,
        close_timeout: float | None = 10,
        max_message_size: int | None = 1024 * 1024,
        ssl: SSLContext | None = None,
    ) -> None:
        """保存连接配置；构造时不发起网络操作。"""
        self._url = url
        self._headers = dict(headers or {})
        self._connect_timeout = connect_timeout
        self._ping_interval = ping_interval
        self._ping_timeout = ping_timeout
        self._close_timeout = close_timeout
        self._max_message_size = max_message_size
        self._ssl = ssl
        self._connection: ClientConnection | None = None
        self._lifecycle_lock = asyncio.Lock()

    @property
    def is_open(self) -> bool:
        """返回底层连接当前是否允许收发消息。"""
        return self._connection is not None and self._connection.state is State.OPEN

    async def connect(self) -> None:
        """建立连接；已连接时直接返回，远端断开后可显式重连。"""
        async with self._lifecycle_lock:
            if self.is_open:
                return
            if self._connection is not None:
                await self._connection.close()
                self._connection = None
            self._connection = await open_connection(
                self._url,
                additional_headers=self._headers,
                open_timeout=self._connect_timeout,
                ping_interval=self._ping_interval,
                ping_timeout=self._ping_timeout,
                close_timeout=self._close_timeout,
                max_size=self._max_message_size,
                ssl=self._ssl,
            )

    async def initialize(self) -> None:
        """由 LilyWhite 启动托管 Bean 时建立连接。"""
        await self.connect()

    async def close(self) -> None:
        """关闭当前连接，允许重复调用。"""
        async with self._lifecycle_lock:
            connection = self._connection
            self._connection = None
            if connection is not None:
                await connection.close()

    async def __aenter__(self) -> WebSocketClient:
        """进入上下文时建立连接。"""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """退出上下文时关闭连接，不抑制业务异常。"""
        await self.close()

    def _require_connection(self) -> ClientConnection:
        """返回已有连接，让底层协议异常保留原始关闭原因。"""
        if self._connection is None:
            raise RuntimeError("WebSocket 客户端尚未连接")
        return self._connection

    async def receive(self, *, timeout: float | None = None) -> str | bytes:
        """接收一条文本或二进制消息，可按需设置秒级超时。"""
        connection = self._require_connection()
        if timeout is None:
            return await connection.recv()
        async with asyncio.timeout(timeout):
            return await connection.recv()

    async def receive_text(self, *, timeout: float | None = None) -> str:
        """接收文本消息，收到二进制消息时明确报错。"""
        message = await self.receive(timeout=timeout)
        if not isinstance(message, str):
            raise TypeError("期望 WebSocket 文本消息，实际收到二进制消息")
        return message

    async def receive_bytes(self, *, timeout: float | None = None) -> bytes:
        """接收二进制消息，收到文本消息时明确报错。"""
        message = await self.receive(timeout=timeout)
        if not isinstance(message, bytes):
            raise TypeError("期望 WebSocket 二进制消息，实际收到文本消息")
        return message

    @overload
    async def receive_json(self, *, timeout: float | None = None) -> object: ...

    @overload
    async def receive_json[T](self, target_type: type[T], *, timeout: float | None = None) -> T: ...

    async def receive_json[T](
        self,
        target_type: type[T] | None = None,
        *,
        timeout: float | None = None,
    ) -> T | object:
        """接收并解码 JSON，可传入 msgspec.Struct 等目标类型。"""
        message = await self.receive(timeout=timeout)
        if target_type is None:
            result: object = msgspec.json.decode(message)
            return result
        return msgspec.json.decode(message, type=target_type)

    async def send_text(self, text: str) -> None:
        """发送一条文本消息。"""
        await self._require_connection().send(text)

    async def send_bytes(self, data: bytes | bytearray | memoryview) -> None:
        """发送一条二进制消息。"""
        await self._require_connection().send(data)

    async def send_json(self, value: object) -> None:
        """把值编码为 JSON 文本消息，支持 msgspec.Struct。"""
        await self.send_text(msgspec.json.encode(value).decode("utf-8"))

    def __aiter__(self) -> WebSocketClient:
        """逐条迭代消息，正常关闭时结束迭代。"""
        return self

    async def __anext__(self) -> str | bytes:
        """等待下一条消息，异常关闭仍保留原始协议异常。"""
        try:
            return await self.receive()
        except ConnectionClosedOK:
            raise StopAsyncIteration from None


__all__ = ["WebSocketClient"]
