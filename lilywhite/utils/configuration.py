"""配置类与同步工厂 Bean 的显式注册装饰器。"""

from collections.abc import Callable, Iterator
from typing import overload

from .registry import Registry

configuration_registry: Registry[type[object]] = Registry()
bean_registry: Registry[Callable[..., object]] = Registry()


def _type_key(target: type[object]) -> str:
    """保留完整模块路径，避免不同包的同名配置类冲突。"""
    return f"{target.__module__}.{target.__qualname__}"


def _factory_key(factory: Callable[..., object]) -> str:
    """保留工厂定义位置，支持不同类中的同名工厂方法。"""
    return f"{factory.__module__}.{factory.__qualname__}"


@overload
def configuration[T](target: type[T]) -> type[T]: ...


@overload
def configuration[T](target: None = None) -> Callable[[type[T]], type[T]]: ...


def configuration[T](target: type[T] | None = None) -> type[T] | Callable[[type[T]], type[T]]:
    """注册一组手动装配规则，不生成代理或修改配置类。"""

    def register(configuration_type: type[T]) -> type[T]:
        configuration_registry.register("configuration", _type_key(configuration_type), configuration_type)
        return configuration_type

    return register if target is None else register(target)


@overload
def bean[F: Callable[..., object]](target: F) -> F: ...


@overload
def bean[F: Callable[..., object]](target: None = None) -> Callable[[F], F]: ...


def bean[F: Callable[..., object]](target: F | None = None) -> F | Callable[[F], F]:
    """把普通方法标记为 Bean 工厂，返回值类型由容器在装配时读取。"""

    def register(factory: F) -> F:
        bean_registry.register("bean", _factory_key(factory), factory)
        return factory

    return register if target is None else register(target)


def registered_configurations(package_names: tuple[str, ...] | None = None) -> Iterator[type[object]]:
    """迭代指定包内的配置类，隔离其他应用的注册残留。"""
    for configuration_type in configuration_registry.by_namespace("configuration"):
        module = configuration_type.__module__
        if package_names is not None and not any(
            module == package or module.startswith(f"{package}.") for package in package_names
        ):
            continue
        yield configuration_type


def registered_bean_methods(configuration_type: type[object]) -> Iterator[Callable[..., object]]:
    """按注册顺序返回当前配置类显式标记的工厂方法。"""
    prefix = f"{_type_key(configuration_type)}."
    for factory in bean_registry.by_namespace("bean"):
        if _factory_key(factory).startswith(prefix):
            yield factory


__all__ = [
    "bean",
    "bean_registry",
    "configuration",
    "configuration_registry",
    "registered_bean_methods",
    "registered_configurations",
]
