"""由应用自动发现和托管的组件生命周期接口。"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class ManagedComponent(Protocol):
    """实现该结构的Singleton由Runtime自动初始化和逆序关闭。"""

    async def initialize(self) -> None:
        """建立组件资源并验证配置或数据库版本。"""
        ...

    async def close(self) -> None:
        """释放组件持有的资源。"""
        ...


@runtime_checkable
class RequestScopedResource(Protocol):
    """需要在当前显式作用域或完整 HTTP 请求结束后释放的资源。"""

    async def close(self) -> None:
        """释放当前作用域持有的资源。"""
        ...


__all__ = ["ManagedComponent", "RequestScopedResource"]
