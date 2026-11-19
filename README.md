# LilyWhite Framework

> 春が来た。
>
> 基于 Litestar + Uvicorn 的 Python 服务端框架。
> 你理解为 **Python 版 Spring** 就行！

装饰器一贴，构造器一写，剩下的交给容器。分层、DI、生命周期、多存储后端，都已经替你备好了。

没有代理、AOP 和字节码魔法，容器本身就是普通 Python 代码，想看随时能看懂。

Lily White 是报春妖精。这个框架也想做点类似的事：把 Spring 的开发体验带进 Python，再涂上一点幻想乡的颜色。

## 先来跑一下

准备 Python 3.14+ 和 uv：

```bash
uv sync
cp -n config.example.yaml config.yaml
uv run python -m example
```

PowerShell 复制配置：

```powershell
Copy-Item config.example.yaml config.yaml
uv run python -m example
```

然后打开：

```text
问候接口  http://127.0.0.1:8000/api/v1/greetings/幻想乡
健康检查  http://127.0.0.1:8000/healthz
请求指标  http://127.0.0.1:8000/metrics
```

启动时会打印彩色 Banner、当前地址和实际启用的后端。

## 写个入口类

```python
# example/application.py
from lilywhite import LilywhiteMain

@LilywhiteMain
class ExampleApplication:
    application_name = "LilyWhite Greeting Example"
    application_version = "0.2.0"
    backends = ("memory",)

    def banner(self) -> str:
        return "春が来た！这是我自己写的 Banner"

    async def on_startup(self) -> None:
        ...

    async def on_shutdown(self) -> None:
        ...
```

`application_name` 和 `application_version` 会出现在默认 Banner 上，`backends` 是默认存储后端。

想用自己的字符画，就写一个返回字符串的 `banner()`。框架会改用它，不再打印默认 Banner；返回内容里也可以带 ANSI 颜色。

想加点自己的启动逻辑，就写 `on_startup()`；需要收拾资源，就写 `on_shutdown()`。同步、异步都可以，框架会把它们接进生命周期。

再用 `run()` 启动：

```python
# example/__main__.py
from lilywhite import run
from .application import ExampleApplication

if __name__ == "__main__":
    run(ExampleApplication)
```

入口类在哪个顶层包，`run()` 就用 AST 扫描哪个包。目录叫 `controller`、`http`、`services`、`logic`、`storage` 还是 `store` 都可以，认的是装饰器，不是文件夹名字。

扫描阶段只解析源码，选出带 `@controller`、`@websocket_controller`、`@service`、`@repository` 或 `@component` 的模块，再精确导入这些模块完成注册。没贴装饰器的普通模块不会为了“碰运气”而全部导入。装饰器起个别名也认，比如 `from lilywhite import service as s` 后的 `@s`。

### 换个 ASGI 服务器也行

`@LilywhiteMain` 会给入口类注入 ASGI `__call__()`，所以入口实例本身就是应用：

```python
import uvicorn
from example.application import ExampleApplication

uvicorn.run(ExampleApplication(), host="127.0.0.1", port=8000)
```

Litestar 应用会在首次调用时创建并缓存，HTTP、WebSocket 和 lifespan 都走同一个实例。外部服务器自己指定监听地址时，Banner 会把地址管理交给它。

## 业务怎么写

装饰器都可以从顶层拿到：

```python
from lilywhite import component, controller, repository, service, websocket_controller
```

### Controller

```python
@controller("/api/v1")
class GreetingController(Controller):
    @get("/greetings/{name:str}")
    async def greeting(self, name: str) -> Response[HttpResult]:
        ...
```

根路径直接写在装饰器里。裸写 `@controller`，默认就是 `/`。

Controller 管 HTTP 参数和结果映射，Service 通过 `NamedDependency[具体Service]` 注入。完整例子在 `example/controller/greeting.py`。

### WebSocket Controller

```python
from litestar.handlers.websocket_handlers import WebsocketListener
from lilywhite import websocket_controller

@websocket_controller("/ws/echo")
class EchoWebsocketController(WebsocketListener):
    async def on_receive(self, data: str) -> str:
        return f"LilyWhite 回声：{data}"
```

它和 `@controller` 一样声明路径并随业务包自动发现，只不过处理的是 WebSocket 消息。可以连接 `ws://127.0.0.1:8000/ws/echo`，发一句“春天来了”试试。

### Service

```python
@service
class GreetingService:
    def __init__(self, greeting_repository: GreetingRepository) -> None:
        self._greeting_repository = greeting_repository
```

需要什么依赖，就写进构造器。Service 里不用关心它来自内存、MySQL 还是别的存储。

### Repository 与 Adapter

接口和实现可以放在任意业务目录，示例里叫 `store/`：

```python
@repository(GreetingRepository, backend="memory")
class MemoryGreetingRepository:
    ...
```

`backend` 直接声明这个 Adapter 属于哪种后端。静态扫描会跳过未启用的 Adapter 模块，不需要再维护 `backend_packages` 或让目录名跟后端名保持一致。这里要写字符串字面量，方便启动前确定导入边界；不同后端继续分模块放，可选依赖就不会被误加载。

启动时选一个，或者多选：

```bash
uv run python -m example --backend memory
uv run python -m example --backend mysql --backend redis
```

容器会按 Repository Interface 找出实现。多个后端同时提供同一个接口时，启动会直接告诉你发生了冲突。

### 托管组件

需要随应用启动和关闭的组件，实现 `ManagedComponent`：

```python
@component
class MyComponent:
    async def initialize(self) -> None: ...
    async def close(self) -> None: ...
```

Singleton 组件会正序启动、逆序关闭，并出现在 `/healthz` 的组件状态里。

## 目录长这样

```text
lilywhite/          框架本体
  app/              入口、ASGI、DI、发现和生命周期
  controller/       Controller、统一结果、SSE 和 HTTP 中间件
  services/         通用 Service、结果模型和 @service
  storage/          @repository 和后端解析
  domain/           通用类型
  observability/    日志历史和异步订阅
  utils/            @component、注册表、任务、时钟和随机源
  config.py         配置模型和 YAML 加载
  logger.py         Loguru 配置
  health.py         组件健康状态
  metrics.py        请求指标
  banner.py         东方主题彩色 Banner

example/            问候示例
  application.py    @LilywhiteMain 入口类
  __main__.py       命令行启动
  controller/       问候 Controller
  services/         问候 Service
  store/            Repository 接口与内存 Adapter（目录名可自由更换）
```

## 配置

`config.example.yaml` 是公共示例，`config.yaml` 留给你自己的环境，不会进 Git。

- `server`：监听地址、端口、CORS。
- `logging`：日志级别、控制台、文件轮转与压缩。
- `operations`：指标窗口和实时日志 Token。

配置分组直接写 `section()`，不用为每个分组再写一个类。字段的范围、长度和正则约束交给 `msgspec.Meta`：

```python
from msgspec import Meta
from lilywhite.config import Config, section, setting

class AppConfig(Config):
    server = section(
        host=setting("127.0.0.1", meta=Meta(min_length=1)),
        port=setting(8000, meta=Meta(ge=0, le=65535)),
    )
```

需要跨字段条件时，再在类上叠加 `@validate("字段路径", lambda ...)`。

读取时仍然是 `config.server.port`。需要覆盖时调用 `override()`，会得到一份独立副本：

```python
config = AppConfig().override(server={"port": 9527})
```

## 开发

```bash
uv sync --locked
uv run pytest tests -q
uv run ruff format --check lilywhite example tests
uv run ruff check lilywhite example tests
uv run mypy
uv build
```

`uv build` 会生成源码包和 wheel，发行包里只有 `lilywhite` 框架本体。
