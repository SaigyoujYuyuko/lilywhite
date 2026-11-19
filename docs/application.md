# 入口与应用生命周期

## `@LilywhiteMain`

入口类负责声明应用元数据、默认后端和可选生命周期钩子：

```python
# my_app/application.py
from lilywhite import LilywhiteMain
from lilywhite.logger import LoggerManager

log = LoggerManager.get_logger("MY_APP")

@LilywhiteMain
class MyApplication:
    application_name = "My LilyWhite App"
    application_version = "0.1.0"
    backends = ("memory",)

    async def on_startup(self) -> None:
        log.info("application startup")

    async def on_shutdown(self) -> None:
        log.info("application shutdown")
```

- `application_name` 和 `application_version` 显示在默认 Banner 上。
- `backends` 是默认启用的 Repository 后端；命令行 `--backend` 可以覆盖它。
- `on_startup()` 和 `on_shutdown()` 可以省略，同步方法和异步方法都可以。

再通过 `run()` 启动：

```python
# my_app/__main__.py
from lilywhite import run
from .application import MyApplication

if __name__ == "__main__":
    run(MyApplication)
```

## 启动参数

```bash
uv run python -m my_app --help
```

| 参数 | 作用 |
| --- | --- |
| `--config PATH` | YAML 配置路径，默认 `config.yaml` |
| `--host HOST` | 覆盖 `server.host` |
| `--port PORT` | 覆盖 `server.port` |
| `--backend NAME` | 启用后端，可重复传入 |
| `--log-level LEVEL` | 覆盖应用日志级别 |
| `--log-file PATH` | 覆盖日志文件路径 |
| `--no-console` | 关闭控制台日志 |

例如同时选择两个后端：

```bash
uv run python -m my_app --backend mysql --backend redis
```

如果同一个 Repository Interface 在两个启用后端中都有实现，容器会在启动时报告冲突。

## Banner

### 默认 Banner 加一句话

只想追加一句话，用 `banner_message()`：

```python
from datetime import datetime

@LilywhiteMain
class MyApplication:
    application_name = "My LilyWhite App"
    application_version = "0.1.0"

    def banner_message(self) -> str:
        hour = datetime.now().astimezone().hour
        message = "Good Morning" if hour < 12 else "Good Afternoon"
        return f"\033[95m       {message}\033[0m"
```

默认字符画、应用版本和启动 URL 都会保留，返回值显示在它们后面。ANSI 颜色可以直接放进字符串。

### 完整替换 Banner

需要自己的字符画时，用 `banner()`：

```python
@LilywhiteMain
class MyApplication:
    def banner(self) -> str:
        return "\033[95m  春が来た！My LilyWhite App\033[0m"
```

`banner()` 会完整替换默认 Banner。它和 `banner_message()` 同时存在时，以 `banner()` 为准。两个方法都必须返回字符串。

## 入口生命周期

`on_startup()` 在框架托管组件启动后执行，适合业务预热、缓存加载或启动检查。

`on_shutdown()` 在托管组件关闭前执行，适合保存业务状态或释放入口类自己管理的资源：

```python
@LilywhiteMain
class MyApplication:
    def on_startup(self) -> None:
        print("同步启动钩子也可以")

    async def on_shutdown(self) -> None:
        print("服务即将关闭")
```

独立关闭钩子会在正常 lifespan 退出时执行。若应用启动中途失败，不会把尚未成功启动的独立关闭钩子当成已完成资源来清理。

组件自己的 `initialize()` / `close()` 见[业务分层与依赖注入](business.md#托管组件)。

## 作为 ASGI 应用运行

`@LilywhiteMain` 会给入口实例注入 ASGI `__call__()`，因此它不依赖 LilyWhite 自己的启动命令。

```python
# asgi.py
from my_app.application import MyApplication

application = MyApplication()
```

```bash
uv run uvicorn asgi:application --host 127.0.0.1 --port 8000
```

也可以直接写 Python：

```python
import uvicorn
from my_app.application import MyApplication

uvicorn.run(MyApplication(), host="127.0.0.1", port=8000)
```

Litestar 应用会在首次 ASGI 调用时创建并缓存，HTTP、WebSocket 和 lifespan 共用同一个实例。外部启动方式仍从工作目录的 `config.yaml` 读取应用配置；监听地址交给外部服务器，Banner 会显示 `ASGI endpoint managed by host server`。

## 手动组合 Litestar 应用

测试、嵌入现有服务或需要直接拿到 Litestar 实例时，可以绕过入口装饰器：

```python
import uvicorn
from lilywhite import LilyWhiteApplication
from lilywhite.config import AppProperties

properties = AppProperties().override(server={"host": "127.0.0.1", "port": 9527})
application = LilyWhiteApplication(
    properties,
    business_package="my_app",
    backends=("memory",),
    application_name="My LilyWhite App",
).create_app()

uvicorn.run(
    application,
    host=properties.server.host,
    port=properties.server.port,
    log_config={"version": 1, "disable_existing_loggers": False},
)
```

`business_package` 是 AST 静态扫描的业务顶层包。不传时只装配框架自带的健康检查和运维接口。
