"""装饰器共享注册表的全限定名和包过滤测试。"""

from lilywhite.decorators.registry import DecoratorRegistry


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
