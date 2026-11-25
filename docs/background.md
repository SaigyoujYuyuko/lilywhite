# 响应后台任务

`@background_task` 用来声明响应结束后的收尾工作，`BackgroundManager` 负责把它绑定到响应、记录执行状态，并在应用关闭时等待已经开始的任务。

它不是持久化任务队列：任务仍在当前进程执行，进程崩溃不会重放。支付、核心数据写入等必须可靠完成的工作不要放在这里。

## 声明任务

普通函数和 `async` 函数都可以。同步函数会放入线程执行，不阻塞事件循环：

```python
# my_app/tasks.py
from lilywhite import background_task


@background_task
async def clear_cache(key: str) -> None:
    await cache.delete(key)


@background_task
def write_access_log(user_id: int) -> None:
    ...
```

任务模块会被框架的 AST 静态扫描自动发现，不需要在入口手动导入或遍历注册表。

## 绑定到响应

把 `BackgroundManager` 注入 Service，在调用处显式传入任务参数。`defer()` 返回 Litestar 的 `BackgroundTask`，直接交给 `response()`、`stream()` 或 `sse()` 的 `background` 参数即可：

```python
from litestar import Response
from lilywhite import BackgroundManager, service
from lilywhite.http.result import response

from ..tasks import clear_cache


@service
class UserService:
    def __init__(self, background: BackgroundManager) -> None:
        self.background = background

    def delete_user(self, user_id: int) -> Response[dict[str, str]]:
        # 删除用户的业务操作在这里完成。
        return response(
            {"message": "deleted"},
            background=self.background.defer(clear_cache, f"user:{user_id}"),
        )
```

未使用 `@background_task` 声明的函数会被 `defer()` 拒绝。任务只会在响应体发送完毕后执行；对 SSE 来说，就是整个事件流结束之后。

需要多个收尾任务时，继续使用 Litestar 的组合方式：

```python
from litestar.background_tasks import BackgroundTasks

background = BackgroundTasks(
    [
        self.background.defer(write_access_log, user_id),
        self.background.defer(clear_cache, f"user:{user_id}"),
    ],
    run_in_task_group=True,
)
return response({"message": "deleted"}, background=background)
```

## 并发与关闭

```yaml
background:
  # 所有响应后台任务共享的全局并发上限；0 表示不限制。
  max_concurrency: 0
```

应用关闭时，管理器先停止接收新任务，再等待已经开始的任务完成。`snapshot()` 返回当前活跃数、累计启动数、完成数和失败数；它与 `AsyncTaskManager` 共用计数，因此也能看到普通 fire-and-forget 异步任务。

任务异常会被记录并计入失败数。后台任务发生在响应之后，异常无法再改变已经发送的状态码和响应体。
