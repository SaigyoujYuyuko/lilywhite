"""问候业务Service与结果示例。"""

import msgspec

from lilywhite import service
from lilywhite.services.result import ServiceResult, success

from ..storage.greeting import GreetingRepository


class GreetingResult(msgspec.Struct, frozen=True):
    """问候用例的公开结果。"""

    message: str


@service
class GreetingService:
    """通过构造器接收Repository并完成问候用例。"""

    def __init__(self, greeting_repository: GreetingRepository) -> None:
        """保存由DI容器注入的Repository Interface。"""
        self._greeting_repository = greeting_repository

    def greet(self, name: str) -> ServiceResult[GreetingResult]:
        """生成问候结果，不包含HTTP或存储实现细节。"""
        return success(GreetingResult(message=self._greeting_repository.greeting(name)))


__all__ = ["GreetingResult", "GreetingService"]
