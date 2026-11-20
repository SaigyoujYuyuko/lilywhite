"""Controller 路径声明与类型注册装饰器。"""

from collections.abc import Callable
from typing import overload

from litestar import Controller

from .registry import DecoratorRegistry

controller_registry: DecoratorRegistry[type[Controller]] = DecoratorRegistry()


@overload
def controller[T](target: type[T], /) -> type[T]: ...


@overload
def controller[T](path: str = "/", /) -> Callable[[type[T]], type[T]]: ...


def controller[T](target_or_path: type[T] | str = "/", /) -> type[T] | Callable[[type[T]], type[T]]:
    """注册 Controller 并声明根路径；支持 @controller 和 @controller("/api/v1")。"""
    path = target_or_path if isinstance(target_or_path, str) else "/"
    if not path.startswith("/"):
        raise ValueError("Controller path 必须以 / 开头")

    def register(target: type[T]) -> type[T]:
        """校验 Controller 子类，设置 Litestar 路径并记录类型。"""
        if not issubclass(target, Controller):
            raise TypeError("@controller 只能用于 Litestar Controller 子类")
        target.path = path  # type: ignore[misc]
        controller_registry.register_type("controller", target)
        return target

    return register if isinstance(target_or_path, str) else register(target_or_path)


def registered_controllers(package_name: str) -> list[type[Controller]]:
    """返回属于指定包的 Controller 类型，不包含其他包的扫描残留。"""
    return list(controller_registry.types_in_packages("controller", (package_name,)))


__all__ = ["controller", "controller_registry", "registered_controllers"]
