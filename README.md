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

## 启动示例

准备 Python 3.14+ 和 uv：

```bash
uv sync
cp -n config.example.yaml config.yaml
uv run python -m lilywhite --config config.yaml
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

参考 `lilywhite/controller/greeting.py`。使用 `@controller("/api/v1")` 同时注册类型并声明根路径；裸写 `@controller` 默认使用 `/`：

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

Interface 放在 `lilywhite/storage/`，具体实现放在后端子包：

```python
@repository(GreetingRepository, backend="memory")
class MemoryGreetingRepository:
    ...
```

后端名称由启动参数选择：

```bash
uv run python -m lilywhite --backend memory
uv run python -m lilywhite --backend mysql --backend redis
```

在 `lilywhite/storage/__init__.py` 的 `backend_packages` 元组中声明后端子包。DI 导入全部启用的后端，并按 Repository Interface 查找唯一实现；同一 Interface 在多个启用后端都有实现时会拒绝启动。未启用 Adapter 的依赖不会导致启动失败。

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
lilywhite/
  app/             应用入口、DI、发现、HTTP和生命周期装配
  controller/      Controller、统一结果、SSE和HTTP中间件
  services/        业务用例、结果模型和@Service
  storage/         Repository Interface、@repository和后端Adapter
  domain/          与框架和存储无关的通用类型
  observability/   有界日志历史和异步订阅
  utils/           @component、注册表、任务、时钟和随机源
  config.py        通用配置模型和YAML加载
  logger.py        Loguru配置和标准日志桥接
  health.py        生命周期与组件健康
  metrics.py       有界请求指标
  __main__.py      命令行启动
```

当前问候模块是完整可运行示例。后续可将示例业务移到独立业务包，由启动器同时扫描框架与业务包。

## 配置

`config.example.yaml` 是公共模板，`config.yaml` 是本机配置且已被 Git 忽略。当前配置版本为 1。

- `server`：监听地址、端口、CORS 来源。
- `logging`：日志级别、第三方过滤、控制台、文件轮转与压缩。
- `operations`：指标窗口和独立日志 Token。

配置分区使用不可变 `msgspec.Struct`。新增配置分区后，DI 容器会自动按具体 Properties 类型注入。

## 开发检查

```bash
uv run ruff format --check lilywhite
uv run ruff check lilywhite
uv run mypy
```

框架可直接运行，不要求安装为 Python 包，也不包含具体游戏业务依赖。
