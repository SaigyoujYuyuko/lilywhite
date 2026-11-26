"""装饰器共享注册表的全限定名、统一依赖元数据和包过滤测试。"""

from lilywhite import component, repository, service
from lilywhite.decorators.component import component_registry, registered_components
from lilywhite.decorators.registry import DecoratorRegistry, DependencyKind
from lilywhite.decorators.repository import registered_repositories, repository_registry
from lilywhite.decorators.service import registered_services, service_registry


def _first_duplicate() -> type[object]:
    """在第一个局部作用域定义同名类。"""

    class Duplicate:
        pass

    return Duplicate


def _second_duplicate() -> type[object]:
    """在第二个局部作用域定义同名类。"""

    class Duplicate:
        pass

    return Duplicate


def test_decorator_registry_separates_same_named_classes() -> None:
    """同名类按完整定义路径共存，并能按业务包筛选。"""
    first = _first_duplicate()
    second = _second_duplicate()
    registry: DecoratorRegistry[type[object]] = DecoratorRegistry()

    registry.register_type("service", first)
    registry.register_type("service", second)

    assert first.__name__ == second.__name__ == "Duplicate"
    assert first.__qualname__ != second.__qualname__
    assert registry.get(f"service.{first.__module__}.{first.__qualname__}") is first
    assert registry.get(f"service.{second.__module__}.{second.__qualname__}") is second
    assert tuple(registry.types_in_packages("service", (__name__,))) == (first, second)
    assert tuple(registry.types_in_packages("service", ("another_application",))) == ()


def test_layered_decorators_share_one_dependency_registry() -> None:
    """三种分层装饰器写入同一注册表，并保留各自角色和兼容查询接口。"""

    @service
    class UnifiedService:
        pass

    @component
    class UnifiedComponent:
        pass

    @repository(UnifiedComponent)
    class UnifiedRepository:
        pass

    service_registration = next(
        item for item in registered_services((__name__,)) if item.implementation is UnifiedService
    )
    component_registration = next(
        item for item in registered_components((__name__,)) if item.implementation is UnifiedComponent
    )
    repository_registration = next(
        item
        for item in registered_repositories(UnifiedComponent, package_names=(__name__,))
        if item.implementation is UnifiedRepository
    )

    assert service_registry is component_registry is repository_registry
    assert service_registration.kind is DependencyKind.SERVICE
    assert service_registration.service_type is UnifiedService
    assert component_registration.kind is DependencyKind.COMPONENT
    assert repository_registration.kind is DependencyKind.REPOSITORY
    assert repository_registration.interface is UnifiedComponent
