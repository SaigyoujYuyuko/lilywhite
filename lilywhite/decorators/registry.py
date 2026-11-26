"""类装饰器共享的条件、依赖元数据、全限定名注册与业务包过滤。"""

from collections.abc import Iterator
from enum import StrEnum
from typing import Any, Protocol, overload

import msgspec

from ..config import AppProperties
from ..utils.registry import LifetimeType, Registry


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


class Condition[Properties = Any](Protocol):
    """接收实际应用配置并返回是否启用的命名谓词。"""

    __name__: str

    def __call__(self, properties: Properties, /) -> bool:
        """根据框架或业务配置计算启用状态。"""
        ...


class ConditionRegistration(msgspec.Struct, frozen=True):
    """统一保存点分配置路径或自定义谓词。"""

    predicate: Condition | None = None
    path: str | None = None

    @property
    def __name__(self) -> str:
        """让通用 Registry 把条件记录视为命名对象。"""
        if self.path is not None:
            return self.path
        if self.predicate is not None:
            return self.predicate.__name__
        raise RuntimeError("条件必须包含配置路径或谓词")

    def evaluate(self, properties: AppProperties) -> bool:
        """从当前配置计算布尔启用状态，并给出具体失败原因。"""
        if self.path is not None:
            try:
                result = properties._read_path(self.path)
            except (KeyError, AttributeError, ValueError) as error:
                raise ValueError(f"启用条件的配置路径不存在：{self.path}") from error
        elif self.predicate is not None:
            result = self.predicate(properties)
        else:
            raise RuntimeError("条件必须包含配置路径或谓词")
        if not isinstance(result, bool):
            raise TypeError(f"启用条件必须返回 bool：{self.__name__}")
        return result


class DependencyKind(StrEnum):
    """共享同一装配能力的三种分层语义。"""

    COMPONENT = "component"
    SERVICE = "service"
    REPOSITORY = "repository"


class DependencyRegistration(msgspec.Struct, frozen=True):
    """Component、Service 和 Repository 共用的完整依赖注册元数据。"""

    kind: DependencyKind
    interface: type[object]
    implementation: type[object]
    lifetime: LifetimeType
    fallback: bool = False
    qualifier: str | None = None
    conditional: ConditionRegistration | None = None

    @property
    def __name__(self) -> str:  # pyright: ignore[reportIncompatibleVariableOverride]
        """让通用 Registry 能把这条元数据记录视为命名对象。"""
        return self.implementation.__name__

    @property
    def service_type(self) -> type[object]:
        """保留 Service 查询接口原有的具体类型名称。"""
        return self.implementation


dependency_registry: Registry[DependencyRegistration] = Registry()


def register_dependency(registration: DependencyRegistration) -> None:
    """按角色和完整类型身份保存注册，避免同名实现互相覆盖。"""
    key = (
        f"{qualified_name(registration.interface)}:{qualified_name(registration.implementation)}:"
        f"{registration.lifetime.value}:{registration.qualifier or ''}"
    )
    dependency_registry.register(registration.kind.value, key, registration)


def registered_dependencies(
    package_names: tuple[str, ...] | None = None,
    *,
    kind: DependencyKind | None = None,
) -> Iterator[DependencyRegistration]:
    """按角色和注册顺序迭代指定包内的统一依赖元数据。"""
    kinds = (kind,) if kind is not None else tuple(DependencyKind)
    for current_kind in kinds:
        for registration in dependency_registry.by_namespace(current_kind.value):
            if module_in_packages(registration.implementation.__module__, package_names):
                yield registration


class DecoratorRegistry[T: type[object]](Registry[T]):
    """为 Controller 等独立类注册表补充全限定名和包过滤。"""

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


__all__ = [
    "Condition",
    "ConditionRegistration",
    "DecoratorRegistry",
    "DependencyKind",
    "DependencyRegistration",
    "QualifiedTarget",
    "dependency_registry",
    "module_in_packages",
    "qualified_name",
    "register_dependency",
    "registered_dependencies",
]
