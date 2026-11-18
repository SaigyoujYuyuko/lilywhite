"""LilyWhite WebSocket 回声示例。"""

from litestar.handlers.websocket_handlers import WebsocketListener

from lilywhite import websocket_controller


@websocket_controller("/ws/echo")
class EchoWebsocketController(WebsocketListener):
    """把收到的文本包装成东方主题回声。"""

    async def on_receive(self, data: str) -> str:
        """返回当前客户端发送的文本。"""
        return f"LilyWhite 回声：{data}"


__all__ = ["EchoWebsocketController"]
