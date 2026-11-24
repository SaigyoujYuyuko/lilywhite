"""ASGI 中间件类声明、签名校验与排序注册。"""

from collections.abc import Callable, Iterator
from inspect import Parameter, iscoroutinefunction, signature
from typing import overload

import msgspec

from ..utils.registry import Registry
from .registry import module_in_packages, qualified_name

middleware_registry: Registry[MiddlewareRegistration] = Registry()


class MiddlewareRegistration(msgspec.Struct, frozen=True):
    """一个中间件类型及其执行顺序。"""

    middleware_type: type[object]
    order: int = 100

    @property
    def __name__(self) -> str:
        """让通用 Registry 能按类型名管理注册记录。"""
        return self.middleware_type.__name__


@overload
def middleware[T](target: type[T], /) -> type[T]: ...


@overload
def middleware[T](target: None = None, *, order: int = 100) -> Callable[[type[T]], type[T]]: ...


def middleware[T](
    target: type[T] | None = None,
    *,
    order: int = 100,
) -> type[T] | Callable[[type[T]], type[T]]:
    """注册 ASGI 中间件；order 越小，越早看到请求。"""
    if isinstance(order, bool) or not isinstance(order, int):
        raise TypeError("middleware order 必须是整数")

    def register(middleware_type: type[T]) -> type[T]:
        """校验 ASGI 协议形状并保存排序元数据。"""
        location = qualified_name(middleware_type)
        call = middleware_type.__dict__.get("__call__")
        if call is None or not iscoroutinefunction(call):
            raise TypeError(f"中间件必须实现 async __call__：{location}")
        parameters = list(signature(call).parameters.values())
        if [parameter.name for parameter in parameters] != ["self", "scope", "receive", "send"]:
            raise TypeError(f"中间件 __call__ 必须接收 scope、receive、send：{location}")
        constructor = middleware_type.__init__
        if constructor is object.__init__:
            raise TypeError(f"中间件构造器必须接收下一层 app：{location}")
        constructor_parameters = list(signature(constructor).parameters.values())
        if len(constructor_parameters) < 2 or constructor_parameters[1].name != "app":
            raise TypeError(f"中间件构造器第一个参数必须是 app：{location}")
        if constructor_parameters[1].kind not in (Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY):
            raise TypeError(f"中间件 app 参数必须支持关键字传参：{location}")
        registration = MiddlewareRegistration(middleware_type, order)
        middleware_registry.register("middleware", qualified_name(middleware_type), registration)
        return middleware_type

    return register if target is None else register(target)


def registered_middlewares(
    package_names: tuple[str, ...] | None = None,
) -> Iterator[MiddlewareRegistration]:
    """按 order 升序迭代，使 Litestar 包装后小 order 位于外层。"""
    discovered = sorted(
        (
            registration
            for registration in middleware_registry.by_namespace("middleware")
            if module_in_packages(registration.middleware_type.__module__, package_names)
        ),
        key=lambda registration: (registration.order, qualified_name(registration.middleware_type)),
    )
    yield from discovered


__all__ = ["MiddlewareRegistration", "middleware", "middleware_registry", "registered_middlewares"]
