"""Service 类型与生命周期注册装饰器。"""

from collections.abc import Callable, Iterator
from typing import overload

import msgspec

from ..utils.registry import LifetimeType
from .registry import DecoratorRegistry

service_registry: DecoratorRegistry[type[object]] = DecoratorRegistry()


class ServiceRegistration(msgspec.Struct, frozen=True):
    """Service 类型及其生命周期。"""

    service_type: type[object]
    lifetime: LifetimeType


def _namespace(lifetime: LifetimeType) -> str:
    """生成按生命周期隔离的 Service 命名空间。"""
    return f"service:{lifetime.value}"


@overload
def service[T](target: type[T], *, lifetime: LifetimeType = LifetimeType.SINGLETON) -> type[T]: ...


@overload
def service[T](
    target: None = None,
    *,
    lifetime: LifetimeType = LifetimeType.SINGLETON,
) -> Callable[[type[T]], type[T]]: ...


def service[T](
    target: type[T] | None = None,
    *,
    lifetime: LifetimeType = LifetimeType.SINGLETON,
) -> type[T] | Callable[[type[T]], type[T]]:
    """注册具体 Service 类型及其生命周期，默认应用级单例。"""

    def register(implementation: type[T]) -> type[T]:
        """记录 Service 类型并保留原始类定义。"""
        service_registry.register_type(_namespace(lifetime), implementation)
        return implementation

    return register if target is None else register(target)


def registered_services(package_names: tuple[str, ...] | None = None) -> Iterator[ServiceRegistration]:
    """按生命周期迭代指定包内已标记的 Service 类型。"""
    for lifetime in LifetimeType:
        for service_type in service_registry.types_in_packages(_namespace(lifetime), package_names):
            yield ServiceRegistration(service_type=service_type, lifetime=lifetime)


__all__ = ["ServiceRegistration", "registered_services", "service", "service_registry"]
