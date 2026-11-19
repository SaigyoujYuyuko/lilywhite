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

命令行只覆盖显式传入的字段，其余值继续来自 YAML。`--no-console` 会关闭控制台输出；`--backend` 覆盖入口类的默认后端。

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
