# 数据库事务与 UnitOfWork

事务有三件不同的事：业务何时成功、数据库怎样提交、连接何时关闭。LilyWhite 把它们放在三个位置：

- **Service**：一次业务用例的最外层是事务边界，决定提交或回滚。
- **Repository**：只使用当前 Session 查询和写入，不自行 `commit()`、`rollback()` 或 `close()`。
- **容器**：创建请求级 Session，并在响应结束、异常、取消或后台任务结束时关闭它。

`UnitOfWork` 封装事务边界：最外层无异常时提交，任意一层异常都会让完整事务回滚。它不拥有连接，也不在上下文退出时关闭 Session。

## SQLAlchemy 装配

```python
from typing import Annotated

from lilywhite import Qualifier, UnitOfWork, bean, configuration
from lilywhite.utils.registry import LifetimeType
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

@configuration
class Persistence:
    @bean(name="primary", close=AsyncEngine.dispose)
    def engine(self) -> AsyncEngine:
        return create_async_engine(
            "postgresql+asyncpg://user:password@localhost/app",
            pool_pre_ping=True,
        )

    @bean(lifetime=LifetimeType.SCOPED, close=AsyncSession.close)
    def session(
        self,
        engine: Annotated[AsyncEngine, Qualifier("primary")],
    ) -> AsyncSession:
        return AsyncSession(engine, expire_on_commit=False)

    @bean(lifetime=LifetimeType.SCOPED)
    def unit_of_work(self, session: AsyncSession) -> UnitOfWork[AsyncSession]:
        return UnitOfWork(session)
```

`AsyncEngine` 是应用级 Singleton；`AsyncSession` 和 `UnitOfWork` 是 Scoped。不要把 Session 注册成 Singleton，也不要把它存到全局变量。

## 多 Repository 用例

```python
@component(lifetime=LifetimeType.SCOPED)
class IdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, user: User) -> None:
        self._session.add(user)

@component(lifetime=LifetimeType.SCOPED)
class BillingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, invoice: Invoice) -> None:
        self._session.add(invoice)

@service(lifetime=LifetimeType.SCOPED)
class CheckoutService:
    def __init__(
        self,
        unit_of_work: UnitOfWork[AsyncSession],
        identity: IdentityRepository,
        billing: BillingRepository,
    ) -> None:
        self.unit_of_work = unit_of_work
        self._identity = identity
        self._billing = billing

    @transactional
    async def checkout(self, user: User, invoice: Invoice) -> None:
        await self._identity.save(user)
        await self._billing.save(invoice)
```

`@transactional` 从顶层 `lilywhite` 导入。它直接包装 async 方法，通过对象公开的 `unit_of_work` 属性复用同一个 UnitOfWork；没有代理类、隐式线程或额外事务规则。同步方法会在声明时被拒绝。需要显式控制事务时，仍可以写 `async with self.unit_of_work:`。

两个 Repository 收到的是同一请求里的同一个 Scoped Session。正常返回时提交一次；任何业务异常、取消或提交失败都会回滚，然后继续向外传播。请求中间件最后关闭 Session，归还连接。

## 嵌套用例

同一个 Scoped `UnitOfWork` 可以嵌套进入，语义类似 Spring 默认的 `REQUIRED`：内层加入当前事务，不创建独立事务，也不会提前 `commit()`。最外层正常退出时才提交一次。

任意一层抛出异常，都会把完整事务标记为 rollback-only。即使外层 Service 捕获内层异常并继续执行，最外层也只会回滚，避免把已经失败的一部分业务连同后续写入一起提交。回滚标记在最外层退出时清理，同一个 UnitOfWork 随后可以用于新的独立用例。

嵌套必须复用同一个 Scoped UnitOfWork；不要用多个独立实例包装同一个 Session。需要“内层失败后保留外层此前写入”的局部恢复时，应使用数据库 SAVEPOINT 的明确 Adapter，而不是依赖 rollback-only 语义。

## 后台任务

后台任务没有 HTTP 请求作用域，必须显式创建和关闭：

```python
async def run_checkout(container: DependencyContainer) -> None:
    scope = container.create_scope()
    try:
        checkout = scope.resolve(CheckoutService)
        await checkout.checkout(user, invoice)
    finally:
        await scope.close()
```

交给 `AsyncTaskManager` 时也保留这个 `try/finally`。每个任务创建自己的 Scope，不能共享 HTTP 请求的 Session。

测试可注入假 Session，检查提交、回滚、关闭顺序；仓库里的 `tests/test_transactions.py` 覆盖了多 Repository、异常和后台任务场景。
