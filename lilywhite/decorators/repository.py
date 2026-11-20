"""Repository Interface、存储实现与生命周期注册装饰器。"""

from collections.abc import Callable

import msgspec

from ..qualifier import qualifier_name
from ..utils.registry import LifetimeType, Registry
from .registry import module_in_packages, qualified_name

repository_registry: Registry[RepositoryRegistration] = Registry()


class RepositoryRegistration(msgspec.Struct, frozen=True):
    """Repository 接口、实现类型、生命周期和可选限定名。"""

    interface: type[object]
    implementation: type[object]
    lifetime: LifetimeType
    qualifier: str | None = None

    @property
    def __name__(self) -> str:  # pyright: ignore[reportIncompatibleVariableOverride]
        """让通用 Registry 能把这条元数据记录视为命名对象。"""
        return self.implementation.__name__


def repository[T](
    interface: type[object],
    *,
    lifetime: LifetimeType = LifetimeType.SINGLETON,
    name: str | None = None,
) -> Callable[[type[T]], type[T]]:
    """把存储实现注册为指定 Interface 的候选实现。"""
    qualifier = qualifier_name(name)

    def register(implementation: type[T]) -> type[T]:
        """记录实现类型并保留原始类定义。"""
        registration = RepositoryRegistration(interface, implementation, lifetime, qualifier)
        key = (
            f"{qualified_name(interface)}:{qualified_name(implementation)}:{lifetime.value}:{qualifier or ''}"
        )
        repository_registry.register("repository", key, registration)
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
        for registration in repository_registry.by_namespace("repository")
        if registration.interface is interface
        and module_in_packages(registration.implementation.__module__, package_names)
    ]


__all__ = ["RepositoryRegistration", "registered_repositories", "repository", "repository_registry"]
