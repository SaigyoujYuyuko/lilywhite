# 多实例与 Qualifier

`@enabled` 解决“这个环境选哪个实现”，`Qualifier` 解决“几个同类型对象要同时存在”。主库和只读库、内部和外部 HTTP Client，都属于后一种。

限定名写在注册处，选择写在注入点。类型仍然说明对象能做什么，名称只说明它是哪一个。

## 多个 HTTP Client

下面用 `httpx.AsyncClient` 注册两个客户端。工厂仍然是普通同步方法，网络连接不需要在工厂里预先建立：

```python
from typing import Annotated

from httpx import AsyncClient
from lilywhite import Qualifier, bean, configuration, service

@configuration
class HttpClients:
    @bean(name="identity")
    def identity_client(self) -> AsyncClient:
        return AsyncClient(base_url="https://identity.example", timeout=5)

    @bean(name="billing")
    def billing_client(self) -> AsyncClient:
        return AsyncClient(base_url="https://billing.example", timeout=10)

@service
class BillingService:
    def __init__(
        self,
        identity: Annotated[AsyncClient, Qualifier("identity")],
        billing: Annotated[AsyncClient, Qualifier("billing")],
    ) -> None:
        self._identity = identity
        self._billing = billing
```

两个 Bean 都是独立的 Singleton。实现 `initialize()` / `close()` 的客户端会分别进入应用生命周期；`AsyncClient` 的关闭适配可以集中在工厂返回的托管对象里完成。

如果只需要容器内解析，也可以显式写名称：

```python
identity = container.resolve(AsyncClient, "identity")
billing = container.resolve(AsyncClient, "billing")
```

请求或后台任务的 `DependencyScope` 使用同样的第二个参数：`scope.resolve(AsyncClient, "billing")`。

## 多个数据库 Engine

数据库 Engine 的写法完全一样：

```python
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

@configuration
class Databases:
    @bean(name="primary")
    def primary_engine(self) -> AsyncEngine:
        return create_async_engine("postgresql+asyncpg://.../main", pool_pre_ping=True)

    @bean(name="replica")
    def replica_engine(self) -> AsyncEngine:
        return create_async_engine("postgresql+asyncpg://.../replica", pool_pre_ping=True)
```

业务对象用 `Annotated[AsyncEngine, Qualifier("primary")]` 和 `Annotated[AsyncEngine, Qualifier("replica")]` 分别接收。请求级 `AsyncSession` 不应跟着 Engine 做成全局 Singleton；事务边界和 Session 生命周期属于后续独立约定。

## 多个 Repository 或 Component

同一 Interface 的多个实现可以同时保持启用：

```python
@repository(GreetingRepository, name="memory")
class MemoryGreetingRepository:
    ...

@repository(GreetingRepository, name="persistent")
class PersistentGreetingRepository:
    ...

@service
class GreetingService:
    def __init__(
        self,
        repository: Annotated[GreetingRepository, Qualifier("persistent")],
    ) -> None:
        self._repository = repository
```

`@component(interface=Cache, name="local")` 和 `@component(interface=Cache, name="remote")` 也使用相同规则。限定名是依赖身份的一部分，所以 Scoped 缓存不会把两个实现混成同一个实例，托管组件的生命周期名称也会带上限定名。

没有写 `name` 的旧代码不需要修改。选择规则只有两条：

- 写了 `Qualifier`，只匹配同名实现；同名重复注册仍会报错。
- 没写 `Qualifier`，要求这个类型只有一个启用候选。存在多个候选，或者候选只有命名实现却没有写 `Qualifier`，都会明确报错。

条件装配会先排除禁用实现，再判断候选。如果只想按环境保留一个 Repository，继续使用 `@enabled` 即可，不必为它发明限定名。

## Controller 注入命名 Bean

命名 Bean 会按限定名加入 Litestar 的依赖表。Controller 组合使用 `NamedDependency` 和 `Annotated`：

```python
from litestar import Controller, get
from litestar.di import NamedDependency
from lilywhite import Qualifier, controller

@controller("/api")
class BillingController(Controller):
    @get("/billing/status")
    async def status(
        self,
        billing: NamedDependency[Annotated[AsyncClient, Qualifier("billing")]],
    ) -> dict[str, str]:
        response = await billing.get("/status")
        return {"status": response.text}
```

Litestar 按**参数名**查找依赖，所以这里的参数名 `billing` 要与 `@bean(name="billing")` 一致；`Qualifier("billing")` 则让业务类型和选择意图保持在同一处。用于 Controller 的限定名应使用合法 Python 标识符。

普通 Service 仍按原来的 `NamedDependency[ConcreteService]` 注入。Component 和 Repository 不直接暴露为 Controller 参数，先注入 Service，保持原来的分层边界。
