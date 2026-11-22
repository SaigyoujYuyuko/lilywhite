# 运维接口与响应

## 健康检查

```text
GET /healthz
```

健康时返回 HTTP 200，非健康时返回 HTTP 503。响应包含运行时间、请求统计和各托管组件状态：

```json
{
  "status": "healthy",
  "uptime_seconds": 12.3,
  "components": {
    "log_stream": {
      "healthy": true,
      "detail": ""
    }
  },
  "requests": {
    "active_requests": 0,
    "total_requests": 8,
    "error_count": 0,
    "error_rate": 0.0
  }
}
```

实现了 `initialize()` / `close()` 的 Singleton Component 会自动加入组件状态。

## 请求指标

```text
GET /metrics
```

指标包含全局与每条路由模板的：

- 当前活跃请求数和峰值。
- 总请求数、错误数和错误率。
- 最近样本的 p50、p99 延迟。
- 每条路由的最大延迟。

`operations.metrics_window_size` 控制全局和每条路由分别保留多少个最近延迟样本。

## SSE 日志流

日志流默认关闭。在本地 `config.yaml` 设置独立的运维 Token：

```yaml
operations:
  log_access_token: replace-with-at-least-32-ascii-characters
```

然后订阅：

```bash
curl -N \
  -H "Authorization: Bearer $LILYWHITE_LOG_TOKEN" \
  http://127.0.0.1:8000/logs/stream
```

接口使用 Server-Sent Events：

- `event: log` 携带日志元数据 JSON。
- 空闲时发送心跳注释，便于连接保活。
- 新订阅会先收到有界历史，再接收实时日志。
- 未配置 Token 返回 404，认证失败返回 401，订阅过多返回 429。

这个 Token 与业务用户认证无关，只保护运维日志流。不要把真实 Token 写进仓库或公开示例。

这条日志流读取的是 Loguru 记录。通过 `override_logger()` 接管框架日志后，自定义 Logger 的记录不会自动出现在这里；需要流式日志时，可以在自己的 Handler 中另行接入。

## HTTP 响应

`lilywhite.http.result` 提供常用响应构造器。关键字字段直接组成 JSON 对象，不需要额外写一层字典：

```python
from lilywhite.http.result import (
    accepted,
    bad_request,
    created,
    no_content,
    not_found,
    ok,
)

return ok(message="春天来了")
return created(id=1)
return accepted(task_id="spring-1")
return no_content()
return bad_request(message="name is required")
return not_found(message="sticker not found")
```

也可以传入字典或业务自己的响应模型，框架不会添加统一信封：

```python
import msgspec
from lilywhite.http.result import ok


class GreetingResult(msgspec.Struct, frozen=True):
    message: str


return ok(GreetingResult(message="春天来了"))
return ok({"message": "春天来了"})
```

`content` 模型和关键字字段不能同时传入。成功和错误 JSON 默认带 `Cache-Control: no-store`；`created` 可以设置 `Location`，`unauthorized` 会携带 Bearer 挑战，`method_not_allowed` 可以设置 `Allow`。

其他构造器还包括 `forbidden`、`conflict`、`payload_too_large`、`too_many_requests`、`internal_server_error`、`bad_gateway` 和 `service_unavailable`。

## 全局异常处理

`@exception_handler(异常类型)` 注册独立处理函数。参数名可以自定义，但必须依次接收 `Request` 和对应异常，异常参数注解要与装饰器类型一致：

```python
from litestar import Request, Response
from lilywhite import exception_handler
from lilywhite.http.result import not_found


@exception_handler(UserNotFoundError)
def user_not_found(request: Request, error: UserNotFoundError) -> Response[object]:
    return not_found(code="user_not_found", message=str(error))
```

需要集中管理时，把 `@exception_handler` 放在类上。类中的每个公开方法从异常参数注解确定映射，私有方法仍可作为普通辅助函数：

```python
@exception_handler
class BusinessExceptionHandlers:
    def __init__(self, messages: ErrorMessageService) -> None:
        self.messages = messages

    def user_not_found(self, request: Request, error: UserNotFoundError) -> Response[object]:
        return not_found(code="user_not_found", message=self.messages.describe(error))

    def invalid_input(self, request: Request, error: InvalidInputError) -> Response[object]:
        return bad_request(code="invalid_input", message=str(error))
```

处理器组是 Singleton，由 DI 容器构造，可以注入其他 Singleton 配置或 Service。所有处理器必须是同步函数并注解返回 `Response`；不支持 async 异常处理器。缺少类型、签名不符、同一异常存在多个处理器都会在启动阶段报错。手动组合应用时，`LilyWhiteApplication(exception_handlers={...})` 仍可显式覆盖装饰器映射。

## 流式响应

`stream()` 依次发送字符串或字节内容块，不添加 SSE 事件格式。同步和异步可迭代对象都可以使用：

```python
from collections.abc import AsyncIterator
from lilywhite.http.result import stream


async def chunks() -> AsyncIterator[str]:
    yield "春天"
    yield "来了"


return stream(chunks())
```

默认媒体类型是 `text/plain`，可以通过 `status`、`headers` 和 `media_type` 调整。文件下载等二进制响应可设置 `media_type="application/octet-stream"`。

## SSE 事件流

`sse()` 可以把任意可 JSON 编码的异步事件流返回为 Server-Sent Events，不依赖日志或其他业务模型：

```python
from collections.abc import AsyncIterator
from lilywhite.http.result import sse


async def events() -> AsyncIterator[dict[str, object] | None]:
    yield {"id": 1, "message": "春天来了"}
    yield None  # 发送 keep-alive 心跳


return sse(events(), event_type="greeting")
```

需要断线重连时，用 `event_id=lambda event: ...` 提供事件 ID；`retry_duration` 和 `headers` 也可以按业务调整。

## 日志级别

应用和第三方日志级别都可以设置为：

```text
TRACE DEBUG INFO WARNING ERROR CRITICAL
```

- `logging.level` 控制应用日志。
- `logging.third_party_level` 控制 Uvicorn 等第三方组件。
- `logging.console` 控制控制台输出。
- `logging.file` 控制文件输出，轮转、保留和压缩由相邻字段控制。
