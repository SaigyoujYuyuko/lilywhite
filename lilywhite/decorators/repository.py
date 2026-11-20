"""Repository Interface、存储实现与生命周期注册装饰器。"""

from collections.abc import Callable

import msgspec

from ..utils.registry import LifetimeType
from .registry import DecoratorRegistry

repository_registry: DecoratorRegistry[type[object]] = DecoratorRegistry()


class RepositoryRegistration(msgspec.Struct, frozen=True):
    """Repository 实现类型及其生命周期。"""

    implementation: type[object]
    lifetime: LifetimeType


def _namespace(interface: type[object], lifetime: LifetimeType) -> str:
    """生成按 Interface 和生命周期隔离的命名空间。"""
    return f"{interface.__module__}.{interface.__qualname__}:{lifetime.value}"


def repository[T](
    interface: type[object],
    *,
    lifetime: LifetimeType = LifetimeType.SINGLETON,
) -> Callable[[type[T]], type[T]]:
    """把存储实现注册为指定 Interface 的候选实现。"""

    def register(implementation: type[T]) -> type[T]:
        """记录实现类型并保留原始类定义。"""
        repository_registry.register_type(_namespace(interface, lifetime), implementation)
        return implementation

    return register


def registered_repositories(
    interface: type[object],
    *,
    package_names: tuple[str, ...] | None = None,
) -> list[RepositoryRegistration]:
    """返回指定包内 Interface 的全部候选实现及生命周期。"""
    return [
        RepositoryRegistration(implementation=implementation, lifetime=lifetime)
        for lifetime in LifetimeType
        for implementation in repository_registry.types_in_packages(
            _namespace(interface, lifetime), package_names
        )
    ]


__all__ = ["RepositoryRegistration", "registered_repositories", "repository", "repository_registry"]
