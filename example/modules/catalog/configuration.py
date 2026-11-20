"""catalog 自己的配置对象装配规则。"""

from lilywhite import bean, configuration, enabled


class CatalogPolicy:
    def __init__(self, limit: int) -> None:
        self.limit = limit


@enabled("features.catalog")
@configuration
class CatalogConfiguration:
    @bean
    def policy(self) -> CatalogPolicy:
        return CatalogPolicy(limit=20)


__all__ = ["CatalogConfiguration", "CatalogPolicy"]
