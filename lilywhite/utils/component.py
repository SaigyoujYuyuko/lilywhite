"""非HTTP业务组件的类型注册装饰器。"""

from collections.abc import Callable, Iterator
from typing import overload

import msgspec

from .registry import LifetimeType

component_registry: dict[str, ComponentRegistration] = {}


class ComponentRegistration(msgspec.Struct, frozen=True):
    """组件公开类型、实现类型、生命周期和后备标记。"""

    interface: type[object]
    implementation: type[object]
    lifetime: LifetimeType
    fallback: bool = False


def _namespace(interface: type[object], implementation: type[object], lifetime: LifetimeType) -> str:
    """按接口、实现和生命周期隔离组件注册。"""
    return (
        f"{interface.__module__}.{interface.__qualname__}:"
        f"{implementation.__module__}.{implementation.__qualname__}:{lifetime.value}"
    )


@overload
def component[T](
    target: type[T],
    *,
    interface: type[object] | None = None,
    lifetime: LifetimeType = LifetimeType.SINGLETON,
    fallback: bool = False,
) -> type[T]: ...


@overload
def component[T](
    target: None = None,
    *,
    interface: type[object] | None = None,
    lifetime: LifetimeType = LifetimeType.SINGLETON,
    fallback: bool = False,
) -> Callable[[type[T]], type[T]]: ...


def component[T](
    target: type[T] | None = None,
    *,
    interface: type[object] | None = None,
    lifetime: LifetimeType = LifetimeType.SINGLETON,
    fallback: bool = False,
) -> type[T] | Callable[[type[T]], type[T]]:
    """注册基础设施组件；fallback 实现只在同接口没有其他绑定时补位。"""

    def register(implementation: type[T]) -> type[T]:
        """记录组件类型而不创建实例。"""
        public_type = interface or implementation
        registration = ComponentRegistration(public_type, implementation, lifetime, fallback)
        component_registry[_namespace(public_type, implementation, lifetime)] = registration
        return implementation

    return register if target is None else register(target)


def registered_components(package_names: tuple[str, ...] | None = None) -> Iterator[ComponentRegistration]:
    """迭代指定包内的组件及其公开 Interface。"""
    for registration in component_registry.values():
        module = registration.implementation.__module__
        if package_names is not None and not any(
            module == package or module.startswith(f"{package}.") for package in package_names
        ):
            continue
        yield registration


__all__ = ["ComponentRegistration", "component", "component_registry", "registered_components"]
