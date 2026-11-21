"""注册表工具"""

from collections.abc import Callable, Iterator
from enum import StrEnum
from typing import Protocol, overload


class LifetimeType(StrEnum):
    """依赖实例生命周期。"""

    SINGLETON = "singleton"
    SCOPED = "scoped"
    TRANSIENT = "transient"


class Named(Protocol):
    """任何拥有 __name__ 的对象（函数、类等），用于生成注册 key。"""

    @property
    def __name__(self) -> str:
        """读取对象名称。"""
        ...


class Registry[T: Named | type[object]]:
    """按 ``namespace.name`` 键注册对象的泛型注册表，可作装饰器工厂使用。"""

    def __init__(self) -> None:
        self._data: dict[str, T] = {}

    @overload
    def __call__(self, arg: None = None) -> Callable[[T], T]: ...
    @overload
    def __call__(self, arg: str) -> Callable[[T], T]: ...
    @overload
    def __call__(self, arg: T) -> T: ...

    def __call__(self, arg: str | T | None = None) -> Callable[[T], T] | T:
        """作装饰器工厂：``@reg`` / ``@reg()`` 用 main 命名空间，``@reg("ns")`` 指定命名空间。"""
        if arg is None:
            return self.decorator("main")
        if isinstance(arg, str):
            return self.decorator(arg)
        return self._register("main", arg)

    def decorator(self, namespace: str = "main") -> Callable[[T], T]:
        """返回把对象注册到指定 ``namespace`` 的装饰器。"""

        def register(obj: T) -> T:
            return self._register(namespace, obj)

        return register

    def register(self, namespace: str, name: str, obj: T) -> T:
        """按显式名称写入 ``namespace.name`` → obj，并原样返回 obj。"""
        self._data[f"{namespace}.{name}"] = obj
        return obj

    def _register(self, namespace: str, obj: T) -> T:
        """按对象名称注册对象。"""
        return self.register(namespace, obj.__name__, obj)

    def get(self, key: str) -> T | None:
        """按键取对象，不存在返回 ``None``。"""
        return self._data.get(key)

    def __getitem__(self, key: str) -> T:
        """按键取对象，不存在抛 ``KeyError``。"""
        return self._data[key]

    def by_namespace(self, namespace: str) -> Iterator[T]:
        """惰性迭代某命名空间下的所有对象。"""
        prefix = f"{namespace}."
        for k, v in self._data.items():
            if k.startswith(prefix):
                yield v


class ManagedRegistry[T: Named | type[object]](Registry[T]):
    """声明一个业务装饰器及其来源，供入口显式加入静态发现。"""

    def __init__(self, decorator: str, source: str) -> None:
        super().__init__()
        if not decorator.isidentifier():
            raise ValueError("托管注册表装饰器名称必须是合法 Python 标识符")
        if not source or source != source.strip():
            raise ValueError("托管注册表来源必须是非空模块路径")
        self.decorator_name = decorator
        self.source = source


type ManagedRegistrySelection = tuple[ManagedRegistry[Named | type[object]], ...]
