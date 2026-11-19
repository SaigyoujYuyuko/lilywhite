# LilyWhite Framework

> 春が来た。
>
> 基于 Litestar + Uvicorn 的 Python 服务端框架。
> 你理解为 **Python 版 Spring** 就行！

装饰器一贴，构造器一写，剩下的交给容器。分层、DI、生命周期、多存储后端，都已经替你备好了。

没有代理、AOP 和字节码魔法。Lily White 是报春妖精，这个框架也把 Spring 的开发体验带进 Python，再涂上一点幻想乡的颜色。

## 最简用法

需要 Python 3.14+ 和 uv：

```bash
uv add lilywhite
```

```python
# my_app/application.py
from lilywhite import LilywhiteMain

@LilywhiteMain
class MyApplication:
    application_name = "My LilyWhite App"
    application_version = "0.1.0"
    backends = ("memory",)
```

```python
# my_app/__main__.py
from lilywhite import run
from .application import MyApplication

if __name__ == "__main__":
    run(MyApplication)
```

```yaml
# config.yaml
version: 1
```

```bash
uv run python -m my_app
```

打开 `http://127.0.0.1:8000/healthz`，应用已经跑起来了。

## 继续写

- [快速上手：第一个接口与仓库示例](docs/getting-started.md)
- [入口、Banner、生命周期与 ASGI](docs/application.md)
- [Controller、Service、Repository 与依赖注入](docs/business.md)
- [YAML 与声明式配置](docs/configuration.md)
- [健康检查、指标、日志流与响应格式](docs/operations.md)
- [文档导航与仓库结构](docs/index.md)

仓库里的 `example/` 是可以直接运行的完整问候应用。
