"""identity 的 HTTP Adapter。"""

from typing import Annotated

from litestar import Controller, get
from litestar.di import NamedDependency
from litestar.params import FromPath

from lilywhite import controller

from .service import IdentityService


@controller("/api/v1/modules/identity")
class IdentityController(Controller):
    @get("/users/{name:str}")
    async def profile(
        self,
        name: Annotated[str, FromPath],
        identity_service: NamedDependency[IdentityService],
    ) -> dict[str, str]:
        return identity_service.profile(name)


__all__ = ["IdentityController"]
