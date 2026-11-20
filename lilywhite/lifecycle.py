"""由应用或显式作用域自动托管的资源生命周期接口。"""

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

type ResourceCloser = Callable[..., Awaitable[None] | None]


@runtime_checkable
class Initializable(Protocol):
    """只需要异步初始化的资源，不要求同时实现关闭方法。"""

    async def initialize(self) -> None:
        """建立资源并验证配置或外部服务版本。"""
        ...


@runtime_checkable
class ManagedComponent(Initializable, Protocol):
    """实现该结构的 Singleton 由 Runtime 自动初始化和逆序关闭。"""

    async def close(self) -> None:
        """释放组件持有的资源。"""
        ...


@runtime_checkable
class RequestScopedResource(Protocol):
    """需要在当前显式作用域或完整 HTTP 请求结束后释放的资源。"""

    async def close(self) -> None:
        """释放当前作用域持有的资源。"""
        ...


async def close_resource(resource: object, closer: ResourceCloser | None = None) -> None:
    """优先使用显式关闭适配器，否则调用资源自身的 close。"""
    if closer is not None:
        result = closer(resource)
    elif isinstance(resource, RequestScopedResource):
        result = resource.close()
    else:
        return
    if result is not None:
        await result


class AdaptedResource:
    """把第三方关闭方法接入生命周期，同时保留对象自身的异步初始化。"""

    def __init__(self, resource: object, closer: ResourceCloser) -> None:
        self._resource = resource
        self._closer = closer

    async def initialize(self) -> None:
        """对象声明了 initialize 时，在启动阶段调用它。"""
        if isinstance(self._resource, Initializable):
            await self._resource.initialize()

    async def close(self) -> None:
        """通过显式函数释放资源，不使用方法名反射。"""
        await close_resource(self._resource, self._closer)


__all__ = [
    "AdaptedResource",
    "Initializable",
    "ManagedComponent",
    "RequestScopedResource",
    "ResourceCloser",
    "close_resource",
]
