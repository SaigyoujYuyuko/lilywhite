"""客户端断开、请求取消和后台任务异常后的资源清理测试。"""

import asyncio

import pytest

from lilywhite.app.DI.container import DependencyContainer
from lilywhite.app.DI.scope import RequestScopeMiddleware
from lilywhite.utils.registry import LifetimeType
from lilywhite.utils.tasks import AsyncTaskManager


class DisconnectResource:
    """记录 ASGI 故障路径是否释放了请求资源。"""

    def __init__(self) -> None:
        self.close_count = 0

    async def close(self) -> None:
        self.close_count += 1


def _container() -> DependencyContainer:
    """创建只包含请求级测试资源的容器。"""
    container = DependencyContainer()
    container.register_service(DisconnectResource, LifetimeType.SCOPED)
    container.build()
    return container


def test_client_disconnect_closes_scope() -> None:
    """ASGI 应用抛出客户端断开异常时，中间件 finally 仍释放资源。"""

    class ClientDisconnect(Exception):
        pass

    async def exercise() -> None:
        container = _container()
        resource: DisconnectResource | None = None

        async def app(scope: dict[str, object], _receive: object, _send: object) -> None:
            nonlocal resource
            dependency_scope = container.create_scope()
            scope[container.request_scope_key] = dependency_scope
            resource = await dependency_scope.resolve(DisconnectResource)
            raise ClientDisconnect

        middleware = RequestScopeMiddleware(app, container)
        with pytest.raises(ClientDisconnect):
            await middleware({"type": "http"}, None, None)
        assert resource is not None
        assert resource.close_count == 1

    asyncio.run(exercise())


def test_request_cancellation_closes_scope() -> None:
    """请求任务被取消后，已创建的 Scoped 实例仍应关闭一次。"""
    resource: DisconnectResource | None = None

    async def exercise() -> None:
        nonlocal resource
        container = _container()
        started = asyncio.Event()

        async def app(scope: dict[str, object], _receive: object, _send: object) -> None:
            nonlocal resource
            dependency_scope = container.create_scope()
            scope[container.request_scope_key] = dependency_scope
            resource = await dependency_scope.resolve(DisconnectResource)
            started.set()
            await asyncio.sleep(60)

        middleware = RequestScopeMiddleware(app, container)
        task = asyncio.create_task(middleware({"type": "http"}, None, None))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert resource is not None
        assert resource.close_count == 1

    asyncio.run(exercise())


def test_background_task_failure_still_closes_its_scope() -> None:
    """fire-and-forget 任务异常由管理器取回，任务自己的 finally 释放作用域。"""

    async def exercise() -> None:
        container = _container()
        manager = AsyncTaskManager()
        await manager.initialize()
        resource: DisconnectResource | None = None

        async def worker() -> None:
            nonlocal resource
            scope = container.create_scope()
            try:
                resource = await scope.resolve(DisconnectResource)
                raise RuntimeError("background failed")
            finally:
                await scope.close()

        task = manager.spawn(worker())
        results = await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)
        assert isinstance(results[0], RuntimeError)
        assert resource is not None and resource.close_count == 1
        assert manager.snapshot().failed_tasks == 1
        await manager.close()

    asyncio.run(exercise())
