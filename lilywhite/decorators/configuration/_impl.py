"""配置类与同步工厂 Bean 的显式注册装饰器。（内部实现）"""

from collections.abc import Callable, Iterator
from typing import overload

import msgspec

from ...lifecycle import ResourceCloser
from ...qualifier import qualifier_name
from ...utils.registry import LifetimeType, Registry
from ..registry import DecoratorRegistry, qualified_name

type BeanFactory = Callable[..., object]


class BeanRegistration(msgspec.Struct, frozen=True):
    """一个 Bean 工厂及其限定名、生命周期和关闭适配器。"""

    factory: BeanFactory
    qualifier: str | None = None
    lifetime: LifetimeType = LifetimeType.SINGLETON
    closer: ResourceCloser | None = None

    @property
    def __name__(self) -> str:  # pyright: ignore[reportIncompatibleVariableOverride]
        """让通用 Registry 能把这条元数据记录视为命名对象。"""
        return self.factory.__name__


configuration_registry: DecoratorRegistry[type[object]] = DecoratorRegistry()
bean_registry: Registry[BeanRegistration] = Registry()


def _type_key(target: type[object]) -> str:
    """保留完整模块路径，避免不同包的同名配置类冲突。"""
    return qualified_name(target)


def _factory_key(factory: BeanFactory) -> str:
    """保留工厂定义位置，支持不同类中的同名工厂方法。"""
    return qualified_name(factory)


@overload
def configuration[T](target: type[T]) -> type[T]: ...


@overload
def configuration[T](target: None = None) -> Callable[[type[T]], type[T]]: ...


def configuration[T](target: type[T] | None = None) -> type[T] | Callable[[type[T]], type[T]]:
    """注册一组手动装配规则，不生成代理或修改配置类。"""

    def register(configuration_type: type[T]) -> type[T]:
        configuration_registry.register_type("configuration", configuration_type)
        return configuration_type

    return register if target is None else register(target)


@overload
def bean[**P, R](
    target: Callable[P, R],
    *,
    name: str | None = None,
    lifetime: LifetimeType = LifetimeType.SINGLETON,
    close: ResourceCloser | None = None,
) -> Callable[P, R]: ...


@overload
def bean[**P, R](
    target: None = None,
    *,
    name: str | None = None,
    lifetime: LifetimeType = LifetimeType.SINGLETON,
    close: ResourceCloser | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]: ...


def bean[**P, R](
    target: Callable[P, R] | None = None,
    *,
    name: str | None = None,
    lifetime: LifetimeType = LifetimeType.SINGLETON,
    close: ResourceCloser | None = None,
) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
    """注册同步 Bean 工厂，并声明实例名称、生命周期和可选关闭适配器。"""
    qualifier = qualifier_name(name)

    def register(factory: Callable[P, R]) -> Callable[P, R]:
        registration = BeanRegistration(factory, qualifier, lifetime, close)
        key = f"{qualifier or ''}:{lifetime.value}:{_factory_key(factory)}"
        bean_registry.register("bean", key, registration)
        return factory

    return register if target is None else register(target)


def registered_configurations(package_names: tuple[str, ...] | None = None) -> Iterator[type[object]]:
    """迭代指定包内的配置类，隔离其他应用的注册残留。"""
    yield from configuration_registry.types_in_packages("configuration", package_names)


def registered_beans(configuration_type: type[object]) -> Iterator[BeanRegistration]:
    """按注册顺序返回当前配置类显式标记的完整工厂元数据。"""
    prefix = f"{_type_key(configuration_type)}."
    for registration in bean_registry.by_namespace("bean"):
        if _factory_key(registration.factory).startswith(prefix):
            yield registration


def registered_bean_methods(configuration_type: type[object]) -> Iterator[BeanFactory]:
    """按注册顺序返回工厂方法，保留只需要函数对象的注册接口。"""
    for registration in registered_beans(configuration_type):
        yield registration.factory


__all__ = [
    "BeanFactory",
    "BeanRegistration",
    "bean",
    "bean_registry",
    "configuration",
    "configuration_registry",
    "registered_bean_methods",
    "registered_beans",
    "registered_configurations",
]
