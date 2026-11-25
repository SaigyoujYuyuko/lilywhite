"""问候业务Service与结果示例。"""

import msgspec
from litestar.background_tasks import BackgroundTask

from lilywhite import BackgroundManager, service

from ..store.greeting import GreetingRepository
from ..tasks import log_greeting


class GreetingResult(msgspec.Struct, frozen=True):
    """问候用例的公开结果。"""

    message: str


@service
class GreetingService:
    """通过构造器接收Repository并完成问候用例。"""

    def __init__(self, greeting_repository: GreetingRepository, background: BackgroundManager) -> None:
        """保存由 DI 容器注入的 Repository 和响应后台任务管理器。"""
        self._greeting_repository = greeting_repository
        self._background = background

    def greet(self, name: str) -> GreetingResult:
        """生成问候结果，不包含HTTP或存储实现细节。"""
        return GreetingResult(message=self._greeting_repository.greeting(name))

    def greeting_log(self, name: str) -> BackgroundTask:
        """声明响应结束后的日志任务，参数仍在调用处显式传递。"""
        return self._background.defer(log_greeting, name)


__all__ = ["GreetingResult", "GreetingService"]
