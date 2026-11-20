# 快速上手

## 运行仓库里的问候示例

准备 Python 3.14+ 和 uv，在仓库根目录执行：

```bash
uv sync
cp -n config.example.yaml config.yaml
uv run python -m example
```

PowerShell：

```powershell
uv sync
Copy-Item config.example.yaml config.yaml
uv run python -m example
```

`config.yaml` 是本地配置，不会进入 Git。启动时会打印东方主题彩色 Banner、当前地址和启用的后端；示例 Banner 还藏了一句按本地时间变化的问候。

试试这些地址：

```text
问候接口  http://127.0.0.1:8000/api/v1/greetings/幻想乡
健康检查  http://127.0.0.1:8000/healthz
请求指标  http://127.0.0.1:8000/metrics
WebSocket ws://127.0.0.1:8000/ws/echo
```

问候接口会经过真实的 Controller → Service → 内存 Repository 调用链，不是写死在路由里的演示字符串。

## 从零写一个应用

### 安装

在自己的项目里执行：

```bash
uv add lilywhite
```

### 目录

先准备下面四个文件。`web` 只是这里的名字，换成 `http` 或 `api` 也可以。

```text
my_app/
  __init__.py
  __main__.py
  application.py
  web/
    __init__.py
    greeting.py
config.yaml
```

### 写一个 Controller

```python
# my_app/web/greeting.py
from litestar import Controller, get
from lilywhite import controller

@controller("/api/v1")
class GreetingController(Controller):
    @get("/hello/{name:str}")
    async def hello(self, name: str) -> dict[str, str]:
        return {"message": f"你好，{name}！"}
```

`@controller("/api/v1")` 声明这一组路由的根路径，`@get` 来自 Litestar。

### 写入口类

```python
# my_app/application.py
from lilywhite import LilywhiteMain

@LilywhiteMain
class MyApplication:
    application_name = "My LilyWhite App"
    application_version = "0.1.0"
```

入口类所在的顶层包就是业务扫描范围。这里会扫描 `my_app`，因此 `my_app/web/greeting.py` 上的 `@controller` 会被发现。

```python
# my_app/__main__.py
from lilywhite import run
from .application import MyApplication

if __name__ == "__main__":
    run(MyApplication)
```

### 加一份最小配置

```yaml
# config.yaml
version: 1
```

其余配置都有默认值。需要修改监听地址、日志或 CORS 时，再补对应字段即可。

### 启动

```bash
uv run python -m my_app
```

现在可以访问：

```text
http://127.0.0.1:8000/api/v1/hello/莉莉白
http://127.0.0.1:8000/healthz
```

也可以指定另一份配置或覆盖端口：

```bash
uv run python -m my_app --config config.yaml --host 127.0.0.1 --port 9527
```

## 接下来

- 要把业务拆成 Controller、Service 和 Repository，看[业务分层与依赖注入](business.md)。
- 要自定义 Banner、启动逻辑或接入其他 ASGI 服务器，看[入口与应用生命周期](application.md)。
- 要补全配置，看[配置文档](configuration.md)。
