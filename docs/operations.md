# 运维接口与响应

## 健康检查

```text
GET /healthz
```

健康时返回 HTTP 200，非健康时返回 HTTP 503。响应包含运行时间、请求统计和各托管组件状态：

```json
{
  "status": 0,
  "body": {
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
  },
  "error_message": ""
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

## 统一 HTTP 响应

`lilywhite.controller.result` 提供常用响应构造器：

```python
from lilywhite.controller.result import (
    accepted,
    bad_request,
    created,
    no_content,
    not_found,
    ok,
)

return ok({"message": "春天来了"})
return created({"id": 1})
return accepted({"task_id": "spring-1"})
return no_content()
return bad_request("name is required")
return not_found("sticker not found")
```

成功 JSON 使用统一信封：

```json
{
  "status": 0,
  "body": {"message": "春天来了"},
  "error_message": ""
}
```

错误响应的 HTTP 状态和业务 `status` 保持一致，例如 400、404 或 429。成功和错误 JSON 默认带 `Cache-Control: no-store`。

其他构造器还包括 `unauthorized`、`forbidden`、`method_not_allowed`、`conflict`、`payload_too_large`、`too_many_requests`、`internal_server_error`、`bad_gateway` 和 `service_unavailable`。

## Service 业务结果

Service 层可以使用不依赖 HTTP 的结果模型：

```python
from lilywhite.services.result import ServiceResult, success

return success({"message": "春天来了"})
return ServiceResult.failure("sticker_not_found", "表情不存在")
```

Controller 再决定如何映射为 HTTP 响应。这样业务错误码不需要和 HTTP 状态类混在一起。

## 日志级别

应用和第三方日志级别都可以设置为：

```text
TRACE DEBUG INFO WARNING ERROR CRITICAL
```

- `logging.level` 控制应用日志。
- `logging.third_party_level` 控制 Uvicorn 等第三方组件。
- `logging.console` 控制控制台输出。
- `logging.file` 控制文件输出，轮转、保留和压缩由相邻字段控制。
