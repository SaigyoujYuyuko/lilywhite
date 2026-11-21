# 托管注册表与业务装饰器发现

`ManagedRegistry` 让业务自己的装饰器进入 LilyWhite 静态发现，例如 Game 命令、任务处理器或消息订阅。注册表声明装饰器名称和定义模块，AST 预扫描自动识别声明；框架不会全局猜测所有 Python 装饰器。

## 声明注册表

```python
# my_app/game/registry.py
from lilywhite import ManagedRegistry
from lilywhite.utils.registry import Named

game_api_registry: ManagedRegistry[Named | type[object]] = ManagedRegistry("game_api", __name__)


def game_api(target):
    game_api_registry.register("command", target.__name__, target)
    return target
```

这里直接注册函数，所以函数天然满足 `Named`。注册其他元数据模型时，模型需要提供 `__name__`，或者沿用 `Registry` 的命名对象约定。

## 自动发现

入口不需要导入或登记这张表：

```python
# my_app/application.py
from lilywhite import LilywhiteMain

@LilywhiteMain
class MyApplication:
    pass
```

业务模块可以只有这个自定义装饰器：

```python
# my_app/game/login.py
from .registry import game_api

@game_api
def login() -> str:
    return "春が来た"
```

启动时，AST 预扫描先找到 `ManagedRegistry("game_api", __name__)`，把 `game_api` 和 `my_app.game.registry` 加入合法来源；正式扫描再找到 `login.py`，在接管请求前精确导入。模块级普通函数、`async def` 和类都支持；绝对导入、别名及相对导入都可以识别。

没有 `on_startup()` 全包导入，也不会拖到第一次请求才懒加载。自动发现只接受字面量装饰器名称，以及 `__name__` 或字符串字面量来源。

动态生成、无法从源码确定的注册表仍可显式声明：

```python
@LilywhiteMain
class MyApplication:
    managed_registries = (game_api_registry,)
```

手动组合应用时也可以传递同一参数：

```python
application = LilyWhiteApplication(
    properties,
    business_package="my_app",
    managed_registries=(game_api_registry,),
)
```

显式注册和自动声明可以同时存在，相同装饰器来源会合并。托管发现只负责导入，装饰器仍负责自己的元数据校验和注册；它不会把函数变成 DI Component，也不会改变原有注册语义。
