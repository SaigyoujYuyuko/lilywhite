"""billing 只通过 identity 的公开 Service 完成跨模块调用。"""

from typing import Annotated

from lilywhite import Qualifier, service

from ..identity import IdentityService
from ..infrastructure import DatabaseEngine, HttpClient
from .repository import InvoiceRepository


@service
class BillingService:
    def __init__(
        self,
        identity_service: IdentityService,
        repository: Annotated[InvoiceRepository, Qualifier("billing_store")],
        engine: Annotated[DatabaseEngine, Qualifier("replica")],
        client: Annotated[HttpClient, Qualifier("billing_http")],
    ) -> None:
        self._identity_service = identity_service
        self._repository = repository
        self._engine = engine
        self._client = client

    def invoice(self, name: str) -> dict[str, str | int]:
        profile = self._identity_service.profile(name)
        return {
            "customer": profile["name"],
            "total": self._repository.total(),
            "engine": self._engine.name,
            "client": self._client.name,
        }


__all__ = ["BillingService"]
