"""非 HTTP 业务组件的类型注册装饰器。"""

from collections.abc import Callable, Iterator
from typing import overload

import msgspec

from ..qualifier import qualifier_name
from ..utils.registry import LifetimeType, Registry
from .registry import module_in_packages

component_registry: Registry[ComponentRegistration] = Registry()


class ComponentRegistration(msgspec.Struct, frozen=True):
    """组件公开类型、实现类型、生命周期、后备标记和可选限定名。"""

    interface: type[object]
    implementation: type[object]
    lifetime: LifetimeType
    fallback: bool = False
    qualifier: str | None = None

    @property
    def __name__(self) -> str:  # pyright: ignore[reportIncompatibleVariableOverride]
        """让通用 Registry 能把这条元数据记录视为命名对象。"""
        return self.implementation.__name__


def _namespace(
    interface: type[object],
    implementation: type[object],
    lifetime: LifetimeType,
    qualifier: str | None,
) -> str:
    """按接口、实现、生命周期和限定名隔离组件注册。"""
    return (
        f"{interface.__module__}.{interface.__qualname__}:"
        f"{implementation.__module__}.{implementation.__qualname__}:{lifetime.value}:{qualifier or ''}"
    )


@overload
def component[T](
    target: type[T],
    *,
    interface: type[object] | None = None,
    lifetime: LifetimeType = LifetimeType.SINGLETON,
    fallback: bool = False,
    name: str | None = None,
) -> type[T]: ...


@overload
def component[T](
    target: None = None,
    *,
    interface: type[object] | None = None,
    lifetime: LifetimeType = LifetimeType.SINGLETON,
    fallback: bool = False,
    name: str | None = None,
) -> Callable[[type[T]], type[T]]: ...


def component[T](
    target: type[T] | None = None,
    *,
    interface: type[object] | None = None,
    lifetime: LifetimeType = LifetimeType.SINGLETON,
    fallback: bool = False,
    name: str | None = None,
) -> type[T] | Callable[[type[T]], type[T]]:
    """注册基础设施组件；fallback 实现只在同接口同限定名没有其他绑定时补位。"""
    qualifier = qualifier_name(name)

    def register(implementation: type[T]) -> type[T]:
        """记录组件类型而不创建实例。"""
        public_type = interface or implementation
        registration = ComponentRegistration(public_type, implementation, lifetime, fallback, qualifier)
        component_registry.register(
            "component", _namespace(public_type, implementation, lifetime, qualifier), registration
        )
        return implementation

    return register if target is None else register(target)


def registered_components(package_names: tuple[str, ...] | None = None) -> Iterator[ComponentRegistration]:
    """迭代指定包内的组件及其公开 Interface。"""
    for registration in component_registry.by_namespace("component"):
        if module_in_packages(registration.implementation.__module__, package_names):
            yield registration


__all__ = ["ComponentRegistration", "component", "component_registry", "registered_components"]
