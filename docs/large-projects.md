# 大型项目组织与资源管理

## 模块边界和依赖方向

仓库的 `example/modules/` 是一个可以直接运行的模块化单体：

```text
modules/
  infrastructure.py       多个 Engine、HTTP Client 的 Configuration
  identity/
    __init__.py           只公开 IdentityService
    controller.py         HTTP Adapter
    service.py            对外用例
    repository.py         模块内部持久化
  billing/
    __init__.py
    controller.py
    service.py            只调用 IdentityService，不碰 UserRepository
    repository.py
  catalog/
    configuration.py      模块自己的 Bean 规则
    service.py
    repository.py
```

Controller 只处理协议，Service 表达业务用例，Repository 属于当前模块。跨模块调用从对方的包顶层导入公开 Service 或业务 Interface；不要把内部 Repository 放进公开 `__all__`，也不要因为目录能相对导入就直接跨层。

`identity` 和 `billing` 都有真实 HTTP 路由；`catalog` 由 `features.catalog` 整体开关控制。配置拆分沿用普通 `section()`：

```python
class ProjectProperties(AppProperties):
    features = section(catalog=False)
    integrations = section(mysql=False, redis=False, kafka=False)
```

## 三种生命周期

- `SINGLETON`：无请求状态的共享对象，例如 Engine、连接池、HTTP Client、时钟。启动时创建并初始化，应用关闭时逆序释放。
- `SCOPED`：一次请求或一个后台任务内共享，例如 AsyncSession、UnitOfWork、当前用户上下文。同一 Scope 内只创建一次，不同 Scope 完全隔离。
- `TRANSIENT`：每次解析都要新对象，例如携带单次调用选项的轻量构建器。若实现 `close()` 或声明关闭适配器，所有实例都会在当前 Scope 末尾释放。

Singleton 不能捕获 Scoped 或 Transient，容器启动时会检查。Scoped 不应写入全局变量；Transient 不适合昂贵的长连接池。请求结束、响应流异常、客户端断开、任务取消都会触发 Scope 清理。

## 第三方资源适配

Bean 工厂保持同步，异步工作放到启动阶段。对象有 `initialize()` 时会自动调用；第三方关闭方法通过函数显式适配，不使用字符串反射。

httpx：

```python
from httpx import AsyncClient

@configuration
class HttpResources:
    @bean(name="billing", close=AsyncClient.aclose)
    def billing_client(self) -> AsyncClient:
        return AsyncClient(base_url="https://billing.example", timeout=10)
```

SQLAlchemy Engine 使用 `close=AsyncEngine.dispose`；新版 redis-py 使用 `close=Redis.aclose`。旧版 Redis 只有 `close()` 时，直接传对应方法即可。同步关闭函数和异步关闭函数都接受。

如果对象同时有自己的 `initialize()` 和第三方 `aclose()`，显式 `close=` 只替换关闭操作，初始化仍会执行。初始化失败时，当前对象先关闭，此前已启动的对象再逆序回滚。多个关闭错误会全部执行并以 `ExceptionGroup` 汇总。

## 可选依赖与导入

把每个第三方集成放在独立模块，并使用字面量配置路径：

```python
# my_app/integrations/mysql.py
from sqlalchemy.ext.asyncio import create_async_engine
from lilywhite import bean, configuration, enabled

@enabled("integrations.mysql")
@configuration
class MySQLConfiguration:
    @bean(close=AsyncEngine.dispose)
    def engine(self) -> AsyncEngine:
        return create_async_engine("postgresql+asyncpg://...")
```

`integrations.mysql: false` 时，AST 扫描会在导入前跳过整个模块，因此不需要安装 SQLAlchemy 或驱动。Redis、Kafka 也按同样方式各放一个模块；不要在一个模块里混入无条件注册的其他类。

字面量 `@enabled("点分.路径")` 和简单成员判断 `@enabled(lambda config: "postgres" in config.storage.enabled_backends)` 都能在导入前求值，支持 `in` 与 `not in`。其他 lambda 或普通谓词函数更灵活，但必须导入模块后计算，所以模块顶层的第三方依赖仍需要安装。Controller 和 WebSocket Controller 不参与条件装配，把可选能力放在它们调用的 Service / Configuration 中。

## 后台任务、测试和多应用

后台任务通过 `container.create_scope()` 创建独立作用域，并用 `try/finally` 关闭；事务写法见[数据库事务](transactions.md)。`AsyncTaskManager` 会持有任务引用、取回异常，并在应用关闭时取消和等待未完成任务。

测试使用 `TestClient` 或 `AsyncTestClient` 的上下文管理器，确保真实启动和关闭都执行。不要只调用路由函数，那无法验证 DI 和清理。

同一进程可以创建多个 `LilyWhiteApplication`。全局装饰器注册表按 `business_package` 过滤，各应用持有独立容器、配置和生命周期；不要把运行状态写进装饰器类变量或模块全局单例。
