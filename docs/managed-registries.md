# 托管注册表与业务装饰器发现

`ManagedRegistry` 让业务自己的装饰器进入 LilyWhite 静态发现，例如 Game 命令、任务处理器或消息订阅。注册表声明装饰器名称和定义模块，入口显式声明使用哪些表；框架不会全局猜测所有 Python 装饰器。

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

## 在入口启用

```python
# my_app/application.py
from lilywhite import LilywhiteMain
from .game.registry import game_api_registry

@LilywhiteMain
class MyApplication:
    managed_registries = (game_api_registry,)
```

业务模块可以只有这个自定义装饰器：

```python
# my_app/game/login.py
from .registry import game_api

@game_api
def login() -> str:
    return "春が来た"
```

启动时，AST 扫描会把 `game_api` 和定义模块 `my_app.game.registry` 加入合法来源，找到 `login.py` 并在接管请求前精确导入。模块级普通函数、`async def` 和类都支持；绝对导入、别名及相对导入都可以识别。

没有写 `on_startup()` 全包导入，也不会拖到第一次请求才懒加载。未在 `managed_registries` 声明的表不会扩大扫描范围。

手动组合应用时传递同一参数：

```python
application = LilyWhiteApplication(
    properties,
    business_package="my_app",
    managed_registries=(game_api_registry,),
)
```

托管发现只负责导入，装饰器仍负责自己的元数据校验和注册；它不会把函数变成 DI Component，也不会改变原有注册语义。
