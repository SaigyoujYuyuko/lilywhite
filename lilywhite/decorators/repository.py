"""Repository Interface、存储实现与生命周期注册装饰器。"""

from collections.abc import Callable

from ..qualifier import qualifier_name
from ..utils.registry import LifetimeType
from .registry import (
    DependencyKind,
    DependencyRegistration,
    dependency_registry,
    register_dependency,
    registered_dependencies,
)

RepositoryRegistration = DependencyRegistration
repository_registry = dependency_registry


def repository[T](
    interface: type[object],
    *,
    lifetime: LifetimeType = LifetimeType.SINGLETON,
    name: str | None = None,
) -> Callable[[type[T]], type[T]]:
    """把存储实现注册为指定 Interface 的候选实现。"""
    qualifier = qualifier_name(name)

    def register(implementation: type[T]) -> type[T]:
        """记录统一 Repository 元数据并保留原始类定义。"""
        registration = DependencyRegistration(
            DependencyKind.REPOSITORY,
            interface,
            implementation,
            lifetime,
            qualifier=qualifier,
        )
        register_dependency(registration)
        return implementation

    return register


def registered_repositories(
    interface: type[object],
    *,
    package_names: tuple[str, ...] | None = None,
) -> list[RepositoryRegistration]:
    """返回指定包内 Interface 的全部候选实现及生命周期。"""
    return [
        registration
        for registration in registered_dependencies(package_names, kind=DependencyKind.REPOSITORY)
        if registration.interface is interface
    ]


__all__ = ["RepositoryRegistration", "registered_repositories", "repository", "repository_registry"]
