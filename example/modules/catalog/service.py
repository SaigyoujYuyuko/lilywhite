"""catalog 公开用例，仅由启用该模块的调用方注入。"""

from typing import Annotated

from lilywhite import Qualifier, enabled, service

from .configuration import CatalogPolicy
from .repository import StickerRepository


@enabled("features.catalog")
@service
class CatalogService:
    def __init__(
        self,
        repository: Annotated[StickerRepository, Qualifier("catalog_store")],
        policy: CatalogPolicy,
    ) -> None:
        self._repository = repository
        self._policy = policy

    def stickers(self) -> list[str]:
        return self._repository.stickers()[: self._policy.limit]


__all__ = ["CatalogService"]
