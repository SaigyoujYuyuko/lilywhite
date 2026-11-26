"""非 HTTP 业务组件的类型注册装饰器。"""

from collections.abc import Callable, Iterator
from typing import overload

from ..qualifier import qualifier_name
from ..utils.registry import LifetimeType
from .conditional import Condition, normalize_condition
from .registry import (
    DependencyKind,
    DependencyRegistration,
    dependency_registry,
    register_dependency,
    registered_dependencies,
)

ComponentRegistration = DependencyRegistration
component_registry = dependency_registry


@overload
def component[T](
    target: type[T],
    *,
    interface: type[object] | None = None,
    lifetime: LifetimeType = LifetimeType.SINGLETON,
    fallback: bool = False,
    name: str | None = None,
    conditional: Condition | str | None = None,
) -> type[T]: ...


@overload
def component[T](
    target: None = None,
    *,
    interface: type[object] | None = None,
    lifetime: LifetimeType = LifetimeType.SINGLETON,
    fallback: bool = False,
    name: str | None = None,
    conditional: Condition | str | None = None,
) -> Callable[[type[T]], type[T]]: ...


def component[T](
    target: type[T] | None = None,
    *,
    interface: type[object] | None = None,
    lifetime: LifetimeType = LifetimeType.SINGLETON,
    fallback: bool = False,
    name: str | None = None,
    conditional: Condition | str | None = None,
) -> type[T] | Callable[[type[T]], type[T]]:
    """注册基础设施组件，支持后备实现以及直接声明的配置路径或谓词条件。"""
    qualifier = qualifier_name(name)
    condition = normalize_condition(conditional) if conditional is not None else None

    def register(implementation: type[T]) -> type[T]:
        """记录统一组件元数据而不创建实例。"""
        public_type = interface or implementation
        registration = DependencyRegistration(
            DependencyKind.COMPONENT,
            public_type,
            implementation,
            lifetime,
            fallback,
            qualifier,
            condition,
        )
        register_dependency(registration)
        return implementation

    return register if target is None else register(target)


def registered_components(package_names: tuple[str, ...] | None = None) -> Iterator[ComponentRegistration]:
    """迭代指定包内的组件及其公开 Interface。"""
    yield from registered_dependencies(package_names, kind=DependencyKind.COMPONENT)


__all__ = ["ComponentRegistration", "component", "component_registry", "registered_components"]
