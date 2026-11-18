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
    application_version = "0.1.0"
    backends = ("memory",)

    async def on_startup(self) -> None:
        ...

    async def on_shutdown(self) -> None:
        ...
```

`application_name` 和 `application_version` 会出现在 Banner 上，`backends` 是默认存储后端。

想加点自己的启动逻辑，就写 `on_startup()`；需要收拾资源，就写 `on_shutdown()`。同步、异步都可以，框架会把它们接进生命周期。

再用 `run()` 启动：

```python
# example/__main__.py
from lilywhite import run
from .application import ExampleApplication

if __name__ == "__main__":
    run(ExampleApplication)
```

入口类在哪个顶层包，`run()` 就扫描哪个包里的 `controller`、`services` 和 `storage`。

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
from lilywhite import component, controller, repository, service
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

### Service

```python
@service
class GreetingService:
    def __init__(self, greeting_repository: GreetingRepository) -> None:
        self._greeting_repository = greeting_repository
```

需要什么依赖，就写进构造器。Service 里不用关心它来自内存、MySQL 还是别的存储。

### Repository 与 Adapter

接口放在业务包的 `storage/`，实现放进对应后端子包：

```python
@repository(GreetingRepository, backend="memory")
class MemoryGreetingRepository:
    ...
```

在 `example/storage/__init__.py` 里声明有哪些后端：

```python
backend_packages = ("memory",)
```

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
  storage/          Repository 接口与内存 Adapter
```

## 配置

`config.example.yaml` 是公共示例，`config.yaml` 留给你自己的环境，不会进 Git。

- `server`：监听地址、端口、CORS。
- `logging`：日志级别、控制台、文件轮转与压缩。
- `operations`：指标窗口和实时日志 Token。

配置分区是不可变的 `msgspec.Struct`。新增分区后，容器可以按具体 Properties 类型注入。

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

## 发布

推送、PR 和 GitHub Release 都会经过 `.github/workflows/publish.yml` 的测试与构建。

发布 Release 时，工作流会进入 `pypi` 环境，通过 Trusted Publishing 上传到 PyPI，不需要在仓库里保存 API Token。Release 标签使用 `v` 加项目版本号，例如 `v0.1.0`。
