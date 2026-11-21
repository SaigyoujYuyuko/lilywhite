"""问候业务Controller填空示例。"""

from typing import Annotated

from litestar import Controller, Response, get
from litestar.di import NamedDependency
from litestar.params import FromPath

from lilywhite import controller
from lilywhite.http.result import ok

from ..services.greeting import GreetingService


@controller("/api/v1")
class GreetingController(Controller):
    """只负责HTTP参数、Service调用和结果映射。"""

    @get("/greetings/{name:str}")
    async def greeting(
        self,
        name: Annotated[str, FromPath],
        greeting_service: NamedDependency[GreetingService],
    ) -> Response[object]:
        """返回指定名字的问候语。"""
        result = greeting_service.greet(name)
        return ok(result.data)


__all__ = ["GreetingController"]
