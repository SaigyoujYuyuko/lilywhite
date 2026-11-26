"""Service 类型与生命周期注册装饰器。"""

from collections.abc import Callable, Iterator
from typing import overload

from ..utils.registry import LifetimeType
from .registry import (
    DependencyKind,
    DependencyRegistration,
    dependency_registry,
    register_dependency,
    registered_dependencies,
)

ServiceRegistration = DependencyRegistration
service_registry = dependency_registry


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
        """记录统一 Service 元数据并保留原始类定义。"""
        registration = DependencyRegistration(
            DependencyKind.SERVICE,
            implementation,
            implementation,
            lifetime,
        )
        register_dependency(registration)
        return implementation

    return register if target is None else register(target)


def registered_services(package_names: tuple[str, ...] | None = None) -> Iterator[ServiceRegistration]:
    """按注册顺序迭代指定包内的统一 Service 元数据。"""
    yield from registered_dependencies(package_names, kind=DependencyKind.SERVICE)


__all__ = ["ServiceRegistration", "registered_services", "service", "service_registry"]
