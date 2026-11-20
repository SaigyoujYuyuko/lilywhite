"""配置类与同步工厂 Bean 的显式注册装饰器。（内部实现）"""

from collections.abc import Callable, Iterator
from typing import Protocol, overload

import msgspec

from ...qualifier import qualifier_name
from ...utils.registry import Registry
from ..registry import DecoratorRegistry, qualified_name


class BeanFactory(Protocol):
    """普通函数和绑定方法都支持的工厂方法协议。"""

    __name__: str
    __module__: str
    __qualname__: str

    def __call__(self, *args: object, **kwargs: object) -> object:
        """接受容器解析后的依赖并创建 Bean。"""
        ...

    def __get__(self, instance: object, owner: type[object] | None = None) -> BeanFactory:
        """把未绑定函数绑定到配置类实例；绑定方法保持原绑定关系。"""
        ...


class BeanRegistration(msgspec.Struct, frozen=True):
    """一个 Bean 工厂及其可选限定名。"""

    factory: BeanFactory
    qualifier: str | None = None

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
def bean[F: BeanFactory](target: F, *, name: str | None = None) -> F: ...


@overload
def bean[F: BeanFactory](target: None = None, *, name: str | None = None) -> Callable[[F], F]: ...


def bean[F: BeanFactory](target: F | None = None, *, name: str | None = None) -> F | Callable[[F], F]:
    """把普通方法标记为 Bean 工厂，可用名称区分相同返回类型。"""
    qualifier = qualifier_name(name)

    def register(factory: F) -> F:
        registration = BeanRegistration(factory, qualifier)
        key = f"{qualifier or ''}:{_factory_key(factory)}"
        bean_registry.register("bean", key, registration)
        return factory

    return register if target is None else register(target)


def registered_configurations(package_names: tuple[str, ...] | None = None) -> Iterator[type[object]]:
    """迭代指定包内的配置类，隔离其他应用的注册残留。"""
    yield from configuration_registry.types_in_packages("configuration", package_names)


def registered_beans(configuration_type: type[object]) -> Iterator[BeanRegistration]:
    """按注册顺序返回当前配置类显式标记的工厂及限定名。"""
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
