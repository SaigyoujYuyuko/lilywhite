# LilyWhite Framework

基于 Litestar 与 Uvicorn 的 Pythonic 服务端框架。保留 Spring 风格的声明式装配体验，但不使用代理、AOP 或隐式字节码增强。

内置：

- 类型驱动 DI 容器、构造器注入和依赖图启动校验。
- `@controller`、`@component`、`@service`、`@repository` 注册装饰器。
- Singleton、Scoped、Transient 生命周期。
- 包扫描、显式类型注册和 Controller 根路径声明。
- 单后端或多后端 Adapter 条件导入与唯一实现解析。
- 应用与托管组件的启动、逆序关闭和健康状态。
- 主线程与其他线程的未捕获异常 CRITICAL 日志钩子。
- 统一 JSON 结果、CORS、请求指标和独立 Token 保护的 SSE 日志流。
- Loguru 控制台/文件日志、通用异步任务、时钟、随机源和 JSON 类型。

## 公开接口

业务代码可以直接从顶层导入装饰器：

```python
from lilywhite import component, controller, repository, service
```

框架内部仍按职责分层：`controller` 位于 Web 层，其他装饰器不会因方便导入而被错误归入 Web 模块。

## 标志性入口类

每个业务项目用 `@LilywhiteMain` 声明入口类：

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

`application_name` 和 `application_version` 用于彩色 Banner，`backends` 声明直接作为 ASGI 应用运行时的默认后端。入口类还可实现可选的 `on_startup()` / `on_shutdown()` 钩子，在框架组件启动完成后初始化业务，并在组件关闭前清理业务资源；同步和异步钩子均可使用。

框架命令行启动：

```python
# example/__main__.py
from lilywhite import run
from .application import ExampleApplication

if __name__ == "__main__":
    run(ExampleApplication)
```

`run()` 根据入口类所在的顶层包自动推导 `controller`、`services`、`storage` 扫描路径，同时加载框架自带的运维模块。未标记的入口类会被拒绝启动。

装饰器还会为入口类注入标准 ASGI `__call__()`，因此同一个入口实例可以直接交给 Uvicorn 或其他 ASGI 服务器：

```python
import uvicorn
from example.application import ExampleApplication

uvicorn.run(ExampleApplication(), host="127.0.0.1", port=8000)
```

入口实例会在首次 ASGI 调用时创建并缓存 Litestar 应用，后续 HTTP、WebSocket 与 lifespan 调用均委托给该应用。外部 ASGI 模式会明确提示监听地址由宿主服务器管理，避免外部端口覆盖后仍展示配置中的旧 URL。

## 启动示例

准备 Python 3.14+ 和 uv：

```bash
uv sync
cp -n config.example.yaml config.yaml
uv run python -m example --config config.yaml
```

PowerShell 使用 `Copy-Item config.example.yaml config.yaml`。

请求示例：

```bash
curl http://127.0.0.1:8000/api/v1/greetings/幻想乡
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/metrics
```

问候接口经过完整的 `Controller → Service → Repository` 注入链，而不是硬编码在 Controller 中。

## 声明业务类型

### Controller

参考 `example/controller/greeting.py`。使用 `@controller("/api/v1")` 同时注册类型并声明根路径；裸写 `@controller` 默认使用 `/`：

```python
@controller("/api/v1")
class GreetingController(Controller):
    @get("/greetings/{name:str}")
    async def greeting(self, name: str) -> Response[HttpResult]:
        ...
```

Controller 只处理 HTTP 参数、调用 Service 并映射结果，通过 `NamedDependency[具体Service]` 接收依赖。只有显式添加 `@controller` 的类型才会被装配。

### Service

```python
@service
class GreetingService:
    def __init__(self, greeting_repository: GreetingRepository) -> None:
        self._greeting_repository = greeting_repository
```

Service 表达完整业务用例，通过构造器接收 Repository Interface 或其他 Service，不依赖 HTTP 和具体数据库。

### Repository 与 Adapter

Interface 放在 `example/storage/`，具体实现放在后端子包：

```python
@repository(GreetingRepository, backend="memory")
class MemoryGreetingRepository:
    ...
```

后端名称由启动参数选择：

```bash
uv run python -m example --backend memory
uv run python -m example --backend mysql --backend redis
```

在 `example/storage/__init__.py` 的 `backend_packages` 元组中声明后端子包。DI 导入全部启用的后端，并按 Repository Interface 查找唯一实现；同一 Interface 在多个启用后端都有实现时会拒绝启动。未启用 Adapter 的依赖不会导致启动失败。

### 托管组件

需要建立和释放资源的组件实现 `ManagedComponent`：

```python
@component
class MyComponent:
    async def initialize(self) -> None: ...
    async def close(self) -> None: ...
```

Singleton 托管组件会自动正序启动、逆序关闭，并加入 `/healthz` 组件状态。构造器只保存依赖，不执行异步 I/O。

## 目录

```text
lilywhite/          通用框架，不包含问候业务
  app/              入口装饰器、ASGI适配、DI、发现和生命周期装配
  controller/       通用Controller、统一结果、SSE和HTTP中间件
  services/         通用Service、结果模型和@Service
  storage/          @repository和后端解析
  domain/           与框架和存储无关的通用类型
  observability/    有界日志历史和异步订阅
  utils/            @component、注册表、任务、时钟和随机源
  config.py         通用配置模型和YAML加载
  logger.py         Loguru配置和标准日志桥接
  health.py         生命周期与组件健康
  metrics.py        有界请求指标

example/            完整问候业务示例
  application.py    @LilywhiteMain 入口类
  __main__.py       命令行启动
  controller/       问候Controller
  services/         问候Service
  storage/          Repository Interface与内存Adapter
```

## 配置

`config.example.yaml` 是公共模板，`config.yaml` 是本机配置且已被 Git 忽略。当前配置版本为 1。

- `server`：监听地址、端口、CORS 来源。
- `logging`：日志级别、第三方过滤、控制台、文件轮转与压缩。
- `operations`：指标窗口和独立日志 Token。

配置分区使用不可变 `msgspec.Struct`。新增配置分区后，DI 容器会自动按具体 Properties 类型注入。

## 开发检查

```bash
uv sync --locked
uv run pytest tests -q
uv run ruff format --check lilywhite example tests
uv run ruff check lilywhite example tests
uv run mypy
uv build
```

框架与示例均可直接运行；`uv build` 同时生成源码包和 wheel，wheel 只包含 `lilywhite` 框架包。

## 发布

`.github/workflows/publish.yml` 在推送、PR 和 GitHub Release 上执行测试、静态检查与构建。只有发布 Release 才会进入 `pypi` 环境并通过 Trusted Publishing 上传到 PyPI，不需要保存 PyPI API Token。

PyPI Publisher 对应值为：项目 `lilywhite`、Owner `SaigyoujYuyuko`、仓库 `lilywhite`、工作流 `publish.yml`、环境 `pypi`。Release 标签必须为 `v` 加 `pyproject.toml` 中的版本号，例如 `v0.1.0`。
