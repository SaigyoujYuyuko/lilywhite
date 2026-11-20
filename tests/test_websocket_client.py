"""出站 WebSocket 客户端的真实连接与应用生命周期测试。"""

import asyncio

import msgspec
from websockets.asyncio.server import ServerConnection, serve

from lilywhite import WebSocketClient
from lilywhite.app.runtime import ApplicationRuntime
from lilywhite.config import AppProperties


class Greeting(msgspec.Struct, frozen=True):
    """用于验证 typed JSON 解码的消息。"""

    message: str


async def _echo(connection: ServerConnection) -> None:
    """原样返回客户端发来的每条消息。"""
    async for message in connection:
        await connection.send(message)


async def _send_and_close(connection: ServerConnection) -> None:
    """发送两条消息后正常关闭连接。"""
    await connection.send("春が来た")
    await connection.send("LilyWhite")
    await connection.close()


def test_websocket_client_exchanges_text_bytes_and_json() -> None:
    """异步上下文应管理连接，并完成文本、字节和 typed JSON 收发。"""

    async def exercise() -> None:
        async with serve(_echo, "127.0.0.1", 0, ping_interval=None) as server:
            port = server.sockets[0].getsockname()[1]
            async with WebSocketClient(f"ws://127.0.0.1:{port}", ping_interval=None) as client:
                assert client.is_open

                await client.send_text("春が来た")
                assert await client.receive_text(timeout=2) == "春が来た"

                await client.send_bytes(b"\x00\xff")
                assert await client.receive_bytes(timeout=2) == b"\x00\xff"

                greeting = Greeting(message="hello")
                await client.send_json(greeting)
                assert await client.receive_json(Greeting, timeout=2) == greeting

                await client.send_json({"kind": "dict"})
                assert await client.receive_json(timeout=2) == {"kind": "dict"}

            assert not client.is_open

    asyncio.run(exercise())


def test_websocket_client_iterates_until_normal_close() -> None:
    """服务端正常关闭时，异步迭代应自然结束而不是抛出关闭异常。"""

    async def exercise() -> None:
        async with serve(_send_and_close, "127.0.0.1", 0, ping_interval=None) as server:
            port = server.sockets[0].getsockname()[1]
            async with WebSocketClient(f"ws://127.0.0.1:{port}", ping_interval=None) as client:
                messages = [message async for message in client]

            assert messages == ["春が来た", "LilyWhite"]
            assert not client.is_open

    asyncio.run(exercise())


def test_websocket_client_follows_application_lifecycle() -> None:
    """运行时应在启动阶段连接，并在关闭阶段释放托管客户端。"""

    async def exercise() -> None:
        async with serve(_echo, "127.0.0.1", 0, ping_interval=None) as server:
            port = server.sockets[0].getsockname()[1]
            client = WebSocketClient(f"ws://127.0.0.1:{port}", ping_interval=None)
            runtime = ApplicationRuntime(AppProperties(), resources={WebSocketClient: client})

            assert not client.is_open
            async with runtime.lifespan:
                assert runtime.container.resolve(WebSocketClient) is client
                assert client.is_open
                await client.send_text("lifecycle")
                assert await client.receive_text(timeout=2) == "lifecycle"

            assert not client.is_open

    asyncio.run(exercise())
