# 业务分层与依赖注入

装饰器都可以从顶层导入：

```python
from lilywhite import component, controller, repository, service, websocket_controller
```

框架自身的装饰器集中在 `lilywhite.decorators`，按职责分成 `controller`、`websocket`、`service`、`repository`、`component` 和 `configuration` 模块；`bean` 与 `configuration` 放在一起，通用条件装配位于 `conditional`。需要按模块阅读或导入时使用：

```python
from lilywhite.decorators.controller import controller
from lilywhite.decorators.service import service
```

这些类装饰器共享 `DecoratorRegistry`，它继承通用 `Registry`，负责全限定名注册和业务包过滤；日常业务代码继续使用顶层导入即可。

LilyWhite 保留分层和构造器注入，但不生成代理类。Controller 调 Service，Service 依赖 Repository Interface，具体 Adapter 由配置条件在装配时决定。

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

扫描只把模块级类当作注册目标；普通工具模块不会被无差别导入。`@configuration` 配置类也会被发现，其中的 `@bean` 方法随类一起注册。直接导入和别名都可以：

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

@repository(GreetingRepository)
class MemoryGreetingRepository:
    def greeting(self, name: str) -> str:
        return f"你好，{name}！"
```

`@repository` 只声明接口的候选实现，不再接收 `backend`。需要按环境或配置选择实现时，使用统一的 `@enabled`：

```python
from lilywhite import enabled, repository

@enabled(lambda config: config.storage.engine == "memory")
@repository(GreetingRepository)
class MemoryGreetingRepository:
    pass

@enabled(lambda config: config.storage.engine == "mysql")
@repository(GreetingRepository)
class MySQLGreetingRepository:
    pass
```

`storage.engine` 是来自实际 `AppProperties` 子类的业务配置。静态扫描只负责发现装饰器模块，条件会在配置加载后、依赖绑定前执行；不要求 Adapter 的目录名具有特殊含义。

同一个 Interface 必须恰好有一个启用的实现。没有实现或存在多个启用实现时，容器都会在启动阶段给出明确错误。

Repository 也支持生命周期：

```python
@repository(
    GreetingRepository,
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

## WebSocket 客户端

`WebSocketClient` 用于相反的方向：让当前应用作为客户端，连接其他 WebSocket 服务端。异步上下文会负责连接和关闭：

```python
from lilywhite import WebSocketClient

async with WebSocketClient("wss://example.com/ws") as client:
    await client.send_text("春が来た")
    reply = await client.receive_text(timeout=5)

    await client.send_json({"type": "greeting", "name": "Lily"})
    result = await client.receive_json(timeout=5)
```

提供的方法：

- `send_text()`、`send_bytes()`、`send_json()` 发送消息；JSON 以文本帧发送。
- `receive()` 返回原始的 `str | bytes`，`receive_text()` 和 `receive_bytes()` 会检查消息类型。
- `receive_json()` 解码 JSON；传入 `msgspec.Struct` 等类型可得到 typed 结果，例如 `await client.receive_json(Greeting)`。
- 所有接收方法都支持可选的 `timeout` 秒数。
- `async for message in client` 持续接收消息，服务端正常关闭时自然结束；异常关闭会保留协议异常。
- `is_open` 表示底层连接当前是否打开。

需要跨整个应用持有长连接时，可以注册为 Bean：

```python
from lilywhite import WebSocketClient, bean, configuration

@configuration
class UpstreamConfiguration:
    @bean
    def upstream_socket(self) -> WebSocketClient:
        return WebSocketClient(
            "wss://example.com/ws",
            headers={"Authorization": "Bearer <token>"},
        )
```

`WebSocketClient` 实现了 `initialize()` 和 `close()`：应用启动时建立连接，连接失败会让启动直接报错，应用关闭时释放连接。之后其他 Service 可以通过构造器按 `WebSocketClient` 类型注入。

一个实例代表一个连接。不要在同一实例上并发启动多个接收循环；临时任务则优先使用局部 `async with`，不为每个任务创建全局 Singleton。

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

框架或扩展可以用 `@component(interface=SomeInterface, fallback=True)` 声明后备实现。普通组件和 Bean 先绑定，后备实现只在该接口仍没有绑定时补位；业务提供替换实现时不需要加 `fallback=True`。

## 文件组件

框架内置 `FileIO`，默认适配器 `AyaFileIO` 使用 AyaFileIO 的 IOCP、io_uring 或 Dispatch I/O 后端。组件本身是无状态 Singleton，每次文件操作都会独立打开并关闭句柄；不要把某个已打开的文件句柄注册成应用级 Singleton。

业务 Service 直接声明 `FileIO` 即可获得默认实现：

```python
from pathlib import Path
from lilywhite import FileIO, service

@service
class ReportService:
    def __init__(self, file_io: FileIO) -> None:
        self._file_io = file_io

    async def load(self) -> str:
        return await self._file_io.read_text(Path("data/report.txt"))
```

整文件读写和复制的写法：

```python
text = await file_io.read_text(path)
count = await file_io.write_text(path, "春が来た！")

data = await file_io.read_bytes(path)
count = await file_io.write_bytes(path, data)
count = await file_io.copy(source, destination)
```

`read_bytes()` 和 `stream()` 也支持 `offset` 与 `size`，可用于文件范围和 Range 响应。`stream()` 每次产生独立的 `bytes`，不需要处理 AyaFileIO 复用缓冲区的生命周期：

```python
async for chunk in file_io.stream(path, offset=1024, size=65536):
    await send_chunk(chunk)
```

上传等异步输入可以交给 `write_stream()`，不需要先拼成一个大型 `bytes`：

```python
count = await file_io.write_stream(path, upload_chunks)
```

字节和文本写入都会处理短写。`write_text()` 返回字符数，其他二进制写入返回字节数。文件访问权限、允许的路径范围和文件名校验仍属于业务层，不要直接把用户输入拼成文件系统路径。

需要换成自己的存储实现时，注册同接口的普通组件即可，内置实现会退出：

```python
from lilywhite import FileIO, component

@component(interface=FileIO)
class OSSFileIO:
    # 在这里实现 FileIO 声明的方法。
    ...
```

返回 `FileIO` 的 `@bean` 和运行时 `resources={FileIO: instance}` 也能替换默认实现。

## 配置类与工厂 Bean

`@component` 适合大多数“给框架一个类，让框架按构造器创建”的场景。需要调用第三方工厂，或者希望通过一段明确的 Python 逻辑创建对象时，再使用 `@configuration` 和 `@bean`：

```python
# my_app/infra/configuration.py
from lilywhite import bean, configuration

@configuration
class BusinessConfiguration:
    @bean
    def settings(self) -> Settings:
        return get_settings()

    @bean
    def engine(self, settings: Settings) -> AsyncEngine:
        return create_async_engine(
            settings.mysql_url,
            pool_pre_ping=True,
            pool_size=settings.mysql_pool_size,
        )
```

配置类构造器必须无参数。依赖写在 `@bean` 方法参数上，容器按参数类型注入；返回类型就是 Bean 的注册类型。上面的 `engine` 会得到由第一个方法创建的 `Settings`。

第一版遵循这些规则：

- 工厂方法使用同步函数，支持 `@bean` 和 `@bean()`。
- Bean 是应用级 Singleton，启动阶段完成依赖图检查并预创建。
- 同一返回类型只能注册一次，不与 Component、Service 或其他 Bean 隐式竞争。
- 返回值实现 `initialize()` / `close()` 时，同样进入托管组件生命周期。
- 不要给同一个类同时加 `@component` 或用 `@bean` 再注册一次，选择一种装配方式即可。

这里的 `@configuration` 是**对象装配规则**，与 `Config` 负责的 YAML、环境变量和字段校验不是一回事。

## 容器会检查什么

启动构造依赖图时，会检查：

- 构造器依赖是否已注册。
- Repository Interface 是否恰好有一个已启用的实现。
- 是否存在循环依赖。
- Singleton 是否捕获了较短生命周期的依赖。
- Singleton 组件的创建是否成功。

问题会在接管请求之前暴露，不需要等某条路由恰好走到才碰运气。
