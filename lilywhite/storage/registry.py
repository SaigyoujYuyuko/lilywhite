"""Repository Interface、存储实现与生命周期注册装饰器。"""

from collections.abc import Callable

import msgspec

from ..utils.registry import LifetimeType, Registry

repository_registry: Registry[type[object]] = Registry()


class RepositoryRegistration(msgspec.Struct, frozen=True):
    """Repository 实现类型及其生命周期。"""

    implementation: type[object]
    lifetime: LifetimeType


def _namespace(interface: type[object], backend: str, lifetime: LifetimeType) -> str:
    """生成按后端、Interface 和生命周期隔离的命名空间。"""
    return f"{backend}:{interface.__module__}.{interface.__qualname__}:{lifetime.value}"


def repository[T](
    interface: type[object],
    *,
    backend: str,
    lifetime: LifetimeType = LifetimeType.SINGLETON,
) -> Callable[[type[T]], type[T]]:
    """把存储实现注册为指定 Interface 在后端下的实现。"""

    def register(implementation: type[T]) -> type[T]:
        """记录实现类型并保留原始类定义。"""
        repository_registry.decorator(_namespace(interface, backend, lifetime))(implementation)
        return implementation

    return register


def registered_repositories(
    interface: type[object],
    backend: str,
    *,
    package_names: tuple[str, ...] | None = None,
) -> list[RepositoryRegistration]:
    """返回指定包内 Interface 在所选后端下的全部实现及生命周期。"""
    return [
        RepositoryRegistration(implementation=implementation, lifetime=lifetime)
        for lifetime in LifetimeType
        for implementation in repository_registry.by_namespace(_namespace(interface, backend, lifetime))
        if package_names is None
        or any(
            implementation.__module__ == package or implementation.__module__.startswith(f"{package}.")
            for package in package_names
        )
    ]


__all__ = ["RepositoryRegistration", "registered_repositories", "repository", "repository_registry"]
