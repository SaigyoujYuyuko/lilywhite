"""全局 HTTP 异常处理函数与处理器组注册。"""

from collections.abc import Callable, Iterator
from inspect import Parameter, iscoroutinefunction, isfunction, signature
from types import FunctionType
from typing import get_origin, get_type_hints, overload

import msgspec
from litestar import Request, Response

from ..utils.registry import Registry
from .registry import module_in_packages, qualified_name

exception_handler_registry: Registry[ExceptionHandlerRegistration] = Registry()


class ExceptionHandlerRegistration(msgspec.Struct, frozen=True):
    """异常类型、处理函数和可选所属处理器组。"""

    exception_type: type[Exception]
    handler: FunctionType
    owner_type: type[object] | None = None

    @property
    def __name__(self) -> str:
        """让通用 Registry 能按处理函数名管理注册记录。"""
        return self.handler.__name__


@overload
def exception_handler(  # type: ignore[overload-overlap]
    exception_type: type[Exception], /
) -> Callable[[FunctionType], FunctionType]: ...


@overload
def exception_handler[T](handler_type: type[T], /) -> type[T]: ...


def exception_handler[T](
    target: type[T],
    /,
) -> type[T] | Callable[[FunctionType], FunctionType]:
    """注册单个异常处理函数，或注册一个由 DI 创建的异常处理器组。"""
    if not isinstance(target, type):
        raise TypeError("@exception_handler 函数形式必须显式提供异常类型")
    if issubclass(target, Exception):
        exception_type = target

        def register(handler: FunctionType) -> FunctionType:
            """校验并注册独立处理函数。"""
            _validate_handler(handler, exception_type, method=False)
            _register(handler, exception_type)
            return handler

        return register

    methods = [
        value for name, value in target.__dict__.items() if not name.startswith("_") and isfunction(value)
    ]
    if not methods:
        raise ValueError(f"异常处理器组至少需要一个公开处理方法：{target.__qualname__}")
    for method in methods:
        method_exception_type = _validate_handler(method, None, method=True)
        _register(method, method_exception_type, owner_type=target)
    return target


def _validate_handler(
    handler: FunctionType,
    expected_exception: type[Exception] | None,
    *,
    method: bool,
) -> type[Exception]:
    """检查同步 Request、异常和 Response 签名，返回处理器对应的异常类型。"""
    location = f"{handler.__module__}.{handler.__qualname__}"
    if iscoroutinefunction(handler):
        raise TypeError(f"异常处理器必须是同步函数：{location}")
    parameters = list(signature(handler).parameters.values())
    expected_count = 3 if method else 2
    if len(parameters) != expected_count:
        raise TypeError(f"异常处理器必须接收 Request 和对应异常：{location}")
    for parameter in parameters:
        if parameter.kind not in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD):
            raise TypeError(f"异常处理器参数必须支持位置传参：{location}.{parameter.name}")

    hints = get_type_hints(handler)
    request_parameter = parameters[1] if method else parameters[0]
    error_parameter = parameters[2] if method else parameters[1]
    request_type = hints.get(request_parameter.name)
    if request_type is not Request and get_origin(request_type) is not Request:
        raise TypeError(f"异常处理器第一个业务参数必须注解为 Request：{location}.{request_parameter.name}")
    error_type = hints.get(error_parameter.name)
    if not isinstance(error_type, type) or not issubclass(error_type, Exception):
        raise TypeError(f"异常处理器异常参数必须注解为 Exception 子类：{location}.{error_parameter.name}")
    if expected_exception is not None and error_type is not expected_exception:
        raise TypeError(f"异常参数注解必须与装饰器异常类型一致：{location}.{error_parameter.name}")
    return_type = hints.get("return")
    if return_type is not Response and get_origin(return_type) is not Response:
        raise TypeError(f"异常处理器必须注解返回 Response：{location}")
    return error_type


def _register(
    handler: FunctionType,
    exception_type: type[Exception],
    *,
    owner_type: type[object] | None = None,
) -> None:
    """保存静态处理函数，处理器组实例推迟到应用装配时解析。"""
    registration = ExceptionHandlerRegistration(exception_type, handler, owner_type)
    exception_handler_registry.register("exception_handler", qualified_name(handler), registration)


def registered_exception_handlers(
    package_names: tuple[str, ...] | None = None,
) -> Iterator[ExceptionHandlerRegistration]:
    """迭代指定业务包内的处理器，并拒绝同一异常的多个映射。"""
    seen: dict[type[Exception], str] = {}
    for registration in exception_handler_registry.by_namespace("exception_handler"):
        if not module_in_packages(registration.handler.__module__, package_names):
            continue
        location = f"{registration.handler.__module__}.{registration.handler.__qualname__}"
        previous = seen.get(registration.exception_type)
        if previous is not None:
            raise ValueError(
                f"异常 {registration.exception_type.__qualname__} 存在多个处理器：{previous} 与 {location}"
            )
        seen[registration.exception_type] = location
        yield registration


def registered_exception_handler_types(
    package_names: tuple[str, ...] | None = None,
) -> Iterator[type[object]]:
    """按声明顺序返回需要由 DI 构造的处理器组类型。"""
    seen: set[type[object]] = set()
    for registration in registered_exception_handlers(package_names):
        owner_type = registration.owner_type
        if owner_type is not None and owner_type not in seen:
            seen.add(owner_type)
            yield owner_type


__all__ = [
    "ExceptionHandlerRegistration",
    "exception_handler",
    "exception_handler_registry",
    "registered_exception_handler_types",
    "registered_exception_handlers",
]
