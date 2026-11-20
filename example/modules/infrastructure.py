"""多个数据库 Engine 和 HTTP Client 的集中装配。"""

from lilywhite import bean, configuration


class DatabaseEngine:
    """本地示例 Engine；生产 Adapter 可换成 SQLAlchemy AsyncEngine。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


class HttpClient:
    """本地示例 Client；生产 Adapter 可换成 httpx.AsyncClient。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


@configuration
class ModuleInfrastructure:
    """同一类型的多个实例用名字区分，并显式声明关闭方法。"""

    @bean(name="primary", close=DatabaseEngine.dispose)
    def primary_engine(self) -> DatabaseEngine:
        return DatabaseEngine("primary")

    @bean(name="replica", close=DatabaseEngine.dispose)
    def replica_engine(self) -> DatabaseEngine:
        return DatabaseEngine("replica")

    @bean(name="identity_http", close=HttpClient.aclose)
    def identity_client(self) -> HttpClient:
        return HttpClient("identity")

    @bean(name="billing_http", close=HttpClient.aclose)
    def billing_client(self) -> HttpClient:
        return HttpClient("billing")


__all__ = ["DatabaseEngine", "HttpClient", "ModuleInfrastructure"]
