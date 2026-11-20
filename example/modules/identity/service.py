"""identity 对外公开的用例，不允许调用方绕过它直接访问 Repository。"""

from typing import Annotated

from lilywhite import Qualifier, service

from ..infrastructure import DatabaseEngine, HttpClient
from .repository import UserRepository


@service
class IdentityService:
    def __init__(
        self,
        repository: Annotated[UserRepository, Qualifier("identity_store")],
        engine: Annotated[DatabaseEngine, Qualifier("primary")],
        client: Annotated[HttpClient, Qualifier("identity_http")],
    ) -> None:
        self._repository = repository
        self._engine = engine
        self._client = client

    def profile(self, name: str) -> dict[str, str]:
        return {
            "name": self._repository.display_name(name),
            "engine": self._engine.name,
            "client": self._client.name,
        }


__all__ = ["IdentityService"]
