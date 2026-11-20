"""catalog 私有存储；禁用时此模块不会被导入。"""

from lilywhite import enabled, repository


class StickerRepository:
    def stickers(self) -> list[str]:
        raise NotImplementedError


@enabled("features.catalog")
@repository(StickerRepository, name="catalog_store")
class MemoryStickerRepository(StickerRepository):
    def stickers(self) -> list[str]:
        return ["春が来た", "Lily White"]


__all__ = ["MemoryStickerRepository", "StickerRepository"]
