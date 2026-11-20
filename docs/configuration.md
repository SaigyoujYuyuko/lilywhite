# 配置

## YAML 文件

`run()` 默认从工作目录读取 `config.yaml`：

```bash
uv run python -m my_app --config config.yaml
```

最小配置只有：

```yaml
version: 1
```

其他字段都有默认值。仓库的 `config.example.yaml` 是完整公共示例，复制为 `config.yaml` 后再修改；本地配置不会进入 Git。

## 完整配置

```yaml
version: 1

server:
  host: 127.0.0.1
  port: 8000
  cors:
    # null 允许直接打开的本地 HTML；[] 关闭 CORS。
    allow_origins: ["null"]

logging:
  level: INFO
  third_party_level: WARNING
  console: true

  # null 关闭文件输出；相对路径以配置文件所在目录为基准。
  file: null
  file_rotation_mb: 10
  file_retention_days: 14

  # zip、gz、bz2、xz；null 表示轮转后不压缩。
  file_compression: zip

operations:
  metrics_window_size: 4096

  # null 关闭 GET /logs/stream。
  # 开启时使用至少 32 个 ASCII 字符的随机值，只放在本地配置中。
  log_access_token: null
```

CORS 来源可以写明确的 HTTP(S) Origin，例如 `https://ops.example.com`。框架会去掉末尾斜杠并拒绝带路径、查询参数或用户信息的无效 Origin。

## 命令行覆盖

```bash
uv run python -m my_app \
  --config config.yaml \
  --host 0.0.0.0 \
  --port 9527 \
  --log-level DEBUG \
  --log-file logs/server.log
```

PowerShell 可以直接写成一行：

```powershell
uv run python -m my_app --config config.yaml --host 0.0.0.0 --port 9527 --log-level DEBUG
```

命令行只覆盖显式传入的字段，其余值继续来自 YAML。`--no-console` 会关闭控制台输出。

## 在代码里读取和覆盖

```python
from pathlib import Path
from lilywhite.config import ConfigLoader

properties = ConfigLoader(Path("config.yaml")).load()

print(properties.server.host)
print(properties.server.port)
print(properties.logging.level)

debug_properties = properties.override(
    server={"port": 9527},
    logging={"level": "DEBUG"},
)
```

`override()` 返回独立副本，原配置不变。未知字段、类型错误和约束错误会直接报告，不会静默接受拼错的配置项。

## 声明自己的配置模型

配置分组使用 `section()`，不用给每个分组再写一个类：

```python
from msgspec import Meta
from lilywhite.config import Config, section, setting

class ProjectConfig(Config):
    server = section(
        host=setting("127.0.0.1", meta=Meta(min_length=1)),
        port=setting(8000, meta=Meta(ge=0, le=65535)),
    )
    greeting = section(
        prefix=setting("你好", meta=Meta(min_length=1, max_length=16)),
    )

config = ProjectConfig()
print(config.server.port)
print(config.greeting.prefix)
```

普通值会直接声明默认值和类型；需要显式类型、转换器或 `msgspec.Meta` 约束时使用 `setting()`。

常用 `Meta` 约束：

- 数值：`gt`、`ge`、`lt`、`le`、`multiple_of`。
- 长度：`min_length`、`max_length`。
- 字符串：`pattern`。

## 跨字段或额外条件

在类上叠加 `@validate()`，第一个参数是属性路径，第二个参数是返回布尔值的条件：

```python
from lilywhite.config import Config, section, setting, validate

@validate("server.port", lambda port: port != 9000)
@validate("greeting.prefix", lambda prefix: not prefix.isspace())
class ProjectConfig(Config):
    server = section(port=setting(8000))
    greeting = section(prefix=setting("你好"))

config = ProjectConfig().override(server={"port": 9527})
```

条件返回 `False` 时会指出校验失败的属性路径。

需要嵌套分组时继续放 `section()`：

```python
class ProjectConfig(Config):
    server = section(
        host="127.0.0.1",
        cors=section(allow_origins=("null",)),
    )

config = ProjectConfig()
print(config.server.cors.allow_origins)
```

`ProjectConfig` 是自己的业务配置模型；框架启动命令使用的内置 HTTP、日志和运维配置仍是 `AppProperties`。

## 业务配置类型与功能开关

需要让业务分组参与框架启动和条件装配时，继承 `AppProperties`，再把它显式传给 `ConfigLoader`：

```python
from lilywhite import AppProperties
from lilywhite.config import ConfigLoader, section, setting

class ProjectProperties(AppProperties):
    features = section(
        ai=setting(False),
        cache=setting(True),
    )

properties = ConfigLoader(Path("config.yaml")).load(ProjectProperties)
```

入口类声明 `properties_type` 后，`run()` 和 ASGI 启动都会使用这份配置类型：

```python
from lilywhite import LilywhiteMain

@LilywhiteMain
class MyApplication:
    properties_type = ProjectProperties
```

对应的 YAML 可以写：

```yaml
version: 1
features:
  ai: true
  cache: false
```

## 条件装配

`@enabled()` 接收点分配置路径或返回 `bool` 的谓词。条件在容器装配时执行，使用实际加载的配置对象；未声明条件的目标始终启用。

简单布尔开关直接写配置路径：

```python
from lilywhite import bean, configuration, enabled

@configuration
@enabled("features.ai")
class AIConfiguration:
    @bean
    def ai_client(self) -> AIClient:
        return AIClient()
```

路径按 `.` 读取嵌套分组，必须指向 `bool` 值。路径不存在或值不是布尔类型时，启动会给出明确错误；不会执行字符串表达式，也不会把文本 `"false"` 当成布尔开关。

条件可以放在配置类、单个 Bean、Component、Service 或 Repository 上。Controller 和 WebSocket Controller 不参与条件装配，误用 `@enabled` 会直接抛出 `TypeError`。多个条件需要组合时直接写 Python 表达式：

```python
@enabled(lambda config: config.features.ai and config.server.host == "127.0.0.1")
```

复杂条件也可以写成带业务配置类型的普通函数：

```python
def ai_enabled(config: ProjectProperties) -> bool:
    return config.features.ai

@enabled(ai_enabled)
```

条件语义：

- 配置类禁用时，整组 Bean 都不注册，也不会创建配置类实例。
- 单个 Bean、Component 或 Service 禁用时，只跳过对应目标。
- Repository 在候选实现绑定前过滤；没有其他启用实现且业务仍依赖该接口时，启动会明确报告依赖未注册。
- 业务组件禁用后，其他启用的后备组件可以补位；后备组件自身也遵守条件。
- 禁用目标不会创建实例或注册生命周期。

不要在 Bean 工厂里返回 `None` 表示禁用，也不要在模块顶层用 `if config...` 包住装饰器类。前者破坏类型约定，后者会把配置加载与模块导入顺序耦合起来。
