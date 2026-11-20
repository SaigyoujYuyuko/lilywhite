"""类装饰器共享的全限定名注册与业务包过滤。"""

from collections.abc import Iterator
from typing import Protocol, overload

from ..utils.registry import Registry


class QualifiedTarget(Protocol):
    """具有完整 Python 定义路径的工厂函数。"""

    __module__: str
    __qualname__: str


@overload
def qualified_name(target: type[object]) -> str: ...


@overload
def qualified_name(target: QualifiedTarget) -> str: ...


def qualified_name(target: type[object] | QualifiedTarget) -> str:
    """返回包含模块和嵌套类路径的稳定注册键。"""
    return f"{target.__module__}.{target.__qualname__}"


def module_in_packages(module: str, package_names: tuple[str, ...] | None) -> bool:
    """判断模块是否属于指定包；None 表示不限定包边界。"""
    return package_names is None or any(
        module == package or module.startswith(f"{package}.") for package in package_names
    )


class DecoratorRegistry[T: type[object]](Registry[T]):
    """为类装饰器补充全限定名注册和包过滤，复用通用 Registry 存储。"""

    def register_type(self, namespace: str, target: T) -> T:
        """按完整定义路径注册类，避免不同模块的同名类互相覆盖。"""
        return self.register(namespace, qualified_name(target), target)

    def types_in_packages(
        self,
        namespace: str,
        package_names: tuple[str, ...] | None = None,
    ) -> Iterator[T]:
        """按注册顺序迭代命名空间内属于指定包的类。"""
        for target in self.by_namespace(namespace):
            if module_in_packages(target.__module__, package_names):
                yield target


__all__ = ["DecoratorRegistry", "QualifiedTarget", "module_in_packages", "qualified_name"]
