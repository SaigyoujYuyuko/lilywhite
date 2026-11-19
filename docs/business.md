# 业务分层与依赖注入

装饰器都可以从顶层导入：

```python
from lilywhite import component, controller, repository, service, websocket_controller
```

LilyWhite 保留分层和构造器注入，但不生成代理类。Controller 调 Service，Service 依赖 Repository Interface，具体 Adapter 由启动时选择的后端决定。

## 目录可以自由命名

一种可能的结构：

```text
my_app/
  application.py
  web/
    greeting.py
  logic/
    greeting.py
  store/
    greeting.py
    memory/
      greeting.py
```

`web`、`logic`、`store` 都不是固定名字。业务入口在哪个顶层包，框架就 AST 解析哪个包，选出带 LilyWhite 装饰器的模块，再精确导入。

扫描只把模块级类当作注册目标；普通工具模块不会被无差别导入。直接导入和别名都可以：

```python
from lilywhite import service as s

@s()
class GreetingService:
    pass
```

```python
import lilywhite as lw

@lw.controller("/api/v1")
class GreetingController:
    pass
```

实际 Controller 仍需继承 Litestar 的 `Controller`。扫描只负责找到模块，装饰器本身仍负责类型检查和注册。

## Controller

下面是仓库示例使用的完整 HTTP 调用链。先是 Controller：

```python
# my_app/web/greeting.py
from typing import Annotated, cast

import msgspec
from litestar import Controller, Response, get
from litestar.di import NamedDependency
from litestar.params import FromPath

from lilywhite import controller
from lilywhite.controller.result import HttpResult, JsonObject, ok
from ..logic.greeting import GreetingService

@controller("/api/v1")
class GreetingController(Controller):
    @get("/greetings/{name:str}")
    async def greeting(
        self,
        name: Annotated[str, FromPath],
        greeting_service: NamedDependency[GreetingService],
    ) -> Response[HttpResult]:
        result = greeting_service.greet(name)
        return ok(cast(JsonObject, msgspec.to_builtins(result.data)))
```

Controller 管 HTTP 参数和结果映射。Service 参数使用 `NamedDependency[具体Service]`，Litestar 会从 LilyWhite 容器提供的依赖表中取值。

裸写 `@controller` 时根路径是 `/`；带路径时必须以 `/` 开头。

## Service

Service 的依赖直接写进构造器：

```python
# my_app/logic/greeting.py
import msgspec

from lilywhite import service
from lilywhite.services.result import ServiceResult, success
from ..store.greeting import GreetingRepository

class GreetingResult(msgspec.Struct, frozen=True):
    message: str

@service
class GreetingService:
    def __init__(self, greeting_repository: GreetingRepository) -> None:
        self._greeting_repository = greeting_repository

    def greet(self, name: str) -> ServiceResult[GreetingResult]:
        return success(GreetingResult(message=self._greeting_repository.greeting(name)))
```

这里依赖的是 `GreetingRepository` Interface，不需要知道数据来自内存、MySQL 还是其他实现。

### Service 生命周期

```python
from lilywhite import service
from lilywhite.utils.registry import LifetimeType

@service(lifetime=LifetimeType.SCOPED)
class RequestGreetingService:
    pass
```

- `SINGLETON`：默认，整个应用共享一个实例。
- `SCOPED`：同一次 HTTP 请求内共享，请求之间隔离。
- `TRANSIENT`：每次解析都创建新实例。

Singleton 不能捕获 Scoped 或 Transient 依赖。容器会在构造依赖图时报告这类生命周期冲突，也会报告缺少实现和循环依赖。

## Repository 与 Adapter

用 `Protocol` 声明业务需要的能力：

```python
# my_app/store/greeting.py
from typing import Protocol

class GreetingRepository(Protocol):
    def greeting(self, name: str) -> str:
        ...
```

内存实现：

```python
# my_app/store/memory/greeting.py
from lilywhite import repository
from ..greeting import GreetingRepository

@repository(GreetingRepository, backend="memory")
class MemoryGreetingRepository:
    def greeting(self, name: str) -> str:
        return f"你好，{name}！"
```

`backend` 声明 Adapter 所属后端。静态扫描会跳过只包含未启用后端的 Adapter 模块，所以不同后端的可选依赖可以继续分模块放置。

`backend` 必须写成字符串字面量：

```python
# 可以静态筛选
@repository(GreetingRepository, backend="memory")

# 无法在导入前确定后端，扫描会给出文件和行号
# @repository(GreetingRepository, backend=selected_backend)
```

不需要 `backend_packages` 声明，也不要求 Adapter 的目录名等于后端名。

入口类可以声明默认后端：

```python
@LilywhiteMain
class MyApplication:
    backends = ("memory",)
```

启动时覆盖：

```bash
uv run python -m my_app --backend memory
uv run python -m my_app --backend mysql --backend redis
```

多个启用后端为同一个 Interface 提供实现时，启动会报告多个实现冲突。

Repository 也支持生命周期：

```python
@repository(
    GreetingRepository,
    backend="memory",
    lifetime=LifetimeType.SINGLETON,
)
class MemoryGreetingRepository:
    pass
```

## WebSocket Controller

```python
# my_app/web/echo.py
from litestar.handlers.websocket_handlers import WebsocketListener
from lilywhite import websocket_controller

@websocket_controller("/ws/echo")
class EchoWebsocketController(WebsocketListener):
    async def on_receive(self, data: str) -> str:
        return f"LilyWhite 回声：{data}"
```

它和 `@controller` 一样声明路径并随业务包发现，只不过处理 WebSocket 消息。连接 `ws://127.0.0.1:8000/ws/echo` 即可测试。

## 托管组件

`@component` 注册不直接暴露给 Controller 的基础设施组件：

```python
# my_app/infra/cache.py
from lilywhite import component

@component
class CacheComponent:
    async def initialize(self) -> None:
        print("cache ready")

    async def close(self) -> None:
        print("cache closed")
```

实现 `initialize()` 和 `close()` 的 Singleton 会自动接入生命周期，不需要显式继承 Protocol：

- 启动时按注册顺序调用 `initialize()`。
- 关闭时逆序调用 `close()`。
- 组件健康状态会出现在 `/healthz`。

Component 默认为自己注册，也可以指定公开 Interface 和生命周期：

```python
@component(interface=CachePort, lifetime=LifetimeType.SINGLETON)
class RedisCacheComponent:
    pass
```

Component 可以注入 Service 或其他组件；需要暴露给 HTTP 参数注入的业务用例则应使用 `@service`。

## 容器会检查什么

启动构造依赖图时，会检查：

- 构造器依赖是否已注册。
- Repository Interface 在所选后端下是否恰好有一个实现。
- 是否存在循环依赖。
- Singleton 是否捕获了较短生命周期的依赖。
- Singleton 组件的创建是否成功。

问题会在接管请求之前暴露，不需要等某条路由恰好走到才碰运气。
