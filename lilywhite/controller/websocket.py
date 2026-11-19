"""WebSocket Controller 路径声明与类型注册装饰器。"""

from collections.abc import Callable
from typing import overload

from litestar.handlers.websocket_handlers import WebsocketListener

from ..utils.registry import Registry

websocket_controller_registry: Registry[type[WebsocketListener]] = Registry()


@overload
def websocket_controller[T](target: type[T], /) -> type[T]: ...


@overload
def websocket_controller[T](path: str = "/", /) -> Callable[[type[T]], type[T]]: ...


def websocket_controller[T](target_or_path: type[T] | str = "/", /) -> type[T] | Callable[[type[T]], type[T]]:
    """注册 WebSocket Listener 并声明路径，支持裸写和带路径两种形式。"""
    path = target_or_path if isinstance(target_or_path, str) else "/"
    if not path.startswith("/"):
        raise ValueError("WebSocket Controller path 必须以 / 开头")

    def register(target: type[T]) -> type[T]:
        """校验监听器类型，设置路径并记录到独立注册表。"""
        if not issubclass(target, WebsocketListener):
            raise TypeError("@websocket_controller 只能用于 Litestar WebsocketListener 子类")
        target.path = path
        websocket_controller_registry.register(
            "websocket_controller", f"{target.__module__}.{target.__qualname__}", target
        )
        return target

    return register if isinstance(target_or_path, str) else register(target_or_path)


def registered_websocket_controllers(package_name: str) -> list[type[WebsocketListener]]:
    """返回指定业务包中显式注册的 WebSocket Controller。"""
    return [
        controller_type
        for controller_type in websocket_controller_registry.by_namespace("websocket_controller")
        if controller_type.__module__ == package_name
        or controller_type.__module__.startswith(f"{package_name}.")
    ]


__all__ = ["registered_websocket_controllers", "websocket_controller", "websocket_controller_registry"]
