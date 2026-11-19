"""非 HTTP 依赖作用域与资源释放测试。"""

import asyncio

from lilywhite.app.container import DependencyContainer
from lilywhite.utils.registry import LifetimeType


class ScopedResource:
    """记录关闭次数的作用域资源。"""

    def __init__(self) -> None:
        self.close_count = 0

    async def close(self) -> None:
        self.close_count += 1


def test_background_scope_reuses_and_closes_scoped_resource() -> None:
    """后台任务应复用 Scoped 实例，并在作用域结束时释放一次。"""

    async def exercise() -> None:
        container = DependencyContainer("memory")
        container.register_service(ScopedResource, LifetimeType.SCOPED)
        container.build()
        scope = container.create_scope()

        resource = scope.resolve(ScopedResource)
        assert scope.resolve(ScopedResource) is resource

        await scope.close()
        await scope.close()
        assert resource.close_count == 1

    asyncio.run(exercise())
