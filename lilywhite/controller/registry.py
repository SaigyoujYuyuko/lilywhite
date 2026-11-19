"""Controller路径声明与类型注册装饰器。"""

from collections.abc import Callable
from typing import overload

from litestar import Controller

controller_registry: dict[str, type[Controller]] = {}


@overload
def controller[T](target: type[T], /) -> type[T]: ...


@overload
def controller[T](path: str = "/", /) -> Callable[[type[T]], type[T]]: ...


def controller[T](target_or_path: type[T] | str = "/", /) -> type[T] | Callable[[type[T]], type[T]]:
    """注册Controller并声明根路径；支持@controller和@controller("/api/v1")。"""
    path = target_or_path if isinstance(target_or_path, str) else "/"
    if not path.startswith("/"):
        raise ValueError("Controller path 必须以 / 开头")

    def register(target: type[T]) -> type[T]:
        """校验Controller子类，设置Litestar路径并记录类型。"""
        if not issubclass(target, Controller):
            raise TypeError("@controller 只能用于 Litestar Controller 子类")
        target.path = path  # type: ignore[misc]
        key = f"{target.__module__}.{target.__qualname__}"
        controller_registry[key] = target
        return target

    return register if isinstance(target_or_path, str) else register(target_or_path)


def registered_controllers(package_name: str) -> list[type[Controller]]:
    """返回属于指定包的Controller类型，不包含其他包的扫描残留。"""
    return [
        controller_type
        for controller_type in controller_registry.values()
        if controller_type.__module__ == package_name
        or controller_type.__module__.startswith(f"{package_name}.")
    ]


__all__ = ["controller", "controller_registry", "registered_controllers"]
