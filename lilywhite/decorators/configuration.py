"""配置类与同步工厂 Bean 的显式注册装饰器。"""

from collections.abc import Callable, Iterator
from typing import Protocol, overload

from ..utils.registry import Registry
from .registry import DecoratorRegistry, qualified_name


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


configuration_registry: DecoratorRegistry[type[object]] = DecoratorRegistry()
bean_registry: Registry[BeanFactory] = Registry()


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
def bean[F: BeanFactory](target: F) -> F: ...


@overload
def bean[F: BeanFactory](target: None = None) -> Callable[[F], F]: ...


def bean[F: BeanFactory](target: F | None = None) -> F | Callable[[F], F]:
    """把普通方法标记为 Bean 工厂，返回值类型由容器在装配时读取。"""

    def register(factory: F) -> F:
        bean_registry.register("bean", _factory_key(factory), factory)
        return factory

    return register if target is None else register(target)


def registered_configurations(package_names: tuple[str, ...] | None = None) -> Iterator[type[object]]:
    """迭代指定包内的配置类，隔离其他应用的注册残留。"""
    yield from configuration_registry.types_in_packages("configuration", package_names)


def registered_bean_methods(configuration_type: type[object]) -> Iterator[BeanFactory]:
    """按注册顺序返回当前配置类显式标记的工厂方法。"""
    prefix = f"{_type_key(configuration_type)}."
    for factory in bean_registry.by_namespace("bean"):
        if _factory_key(factory).startswith(prefix):
            yield factory


__all__ = [
    "BeanFactory",
    "bean",
    "bean_registry",
    "configuration",
    "configuration_registry",
    "registered_bean_methods",
    "registered_configurations",
]
