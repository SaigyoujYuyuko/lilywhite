# LilyWhite Framework

> 春が来た。
>
> 基于 Litestar 和 Uvicorn 的 Python Web 框架。
> 想要 Spring 的分层和依赖注入，又不想在 Python 里写一堆 Builder，可以试试。

`@controller`、`@service`、`@repository` 和 `@component` 用来声明组件。构造器写清依赖，容器负责创建和清理。存储实现可以通过配置切换，启动时也不用再手动 import 一堆模块。

名字和 `春が来た。` 都来自东方 Project 的报春妖精 Lily White。框架不生成代理，也不靠 AOP 隐藏调用过程。函数在哪里调用、对象在哪里创建，都能顺着代码找到。

## 快速开始

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

打开 `http://127.0.0.1:8000/healthz`，就能看到健康检查结果。

仓库里的 `example/` 是能直接运行的问候应用：

```bash
uv run python -m example
```

## 文档

- [快速上手：第一个接口与仓库示例](docs/getting-started.md)
- [入口、Banner、生命周期与 ASGI](docs/application.md)
- [Controller、Service、Repository 与依赖注入](docs/business.md)
- [多数据库、多客户端与 Qualifier](docs/qualifier.md)
- [业务装饰器与托管注册表](docs/managed-registries.md)
- [事务、模块化与资源生命周期](docs/large-projects.md)
- [声明式响应后台任务](docs/background.md)
- [YAML 与声明式配置](docs/configuration.md)
- [健康检查、指标、日志流与响应格式](docs/operations.md)
- [性能基准与文件场景](docs/performance.md)
- [文档导航与仓库结构](docs/index.md)
