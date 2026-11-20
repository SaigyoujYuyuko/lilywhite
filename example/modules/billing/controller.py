"""billing 的 HTTP Adapter。"""

from typing import Annotated

from litestar import Controller, get
from litestar.di import NamedDependency
from litestar.params import FromPath

from lilywhite import controller

from .service import BillingService


@controller("/api/v1/modules/billing")
class BillingController(Controller):
    @get("/invoices/{name:str}")
    async def invoice(
        self,
        name: Annotated[str, FromPath],
        billing_service: NamedDependency[BillingService],
    ) -> dict[str, str | int]:
        return billing_service.invoice(name)


__all__ = ["BillingController"]
