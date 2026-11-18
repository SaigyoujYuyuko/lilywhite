"""问候业务Controller填空示例。"""

from typing import cast

import msgspec
from litestar import Controller, Response, get
from litestar.di import NamedDependency

from lilywhite import controller
from lilywhite.controller.result import HttpResult, JsonObject, ok

from ..services.greeting import GreetingService


@controller("/api/v1")
class GreetingController(Controller):
    """只负责HTTP参数、Service调用和结果映射。"""

    @get("/greetings/{name:str}")
    async def greeting(
        self,
        name: str,
        greeting_service: NamedDependency[GreetingService],
    ) -> Response[HttpResult]:
        """返回指定名字的问候语。"""
        result = greeting_service.greet(name)
        return ok(cast(JsonObject, msgspec.to_builtins(result.data)))


__all__ = ["GreetingController"]
