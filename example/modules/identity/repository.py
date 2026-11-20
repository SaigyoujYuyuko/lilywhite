"""identity 模块私有持久化接口与内存 Adapter。"""

from lilywhite import repository


class UserRepository:
    def display_name(self, name: str) -> str:
        raise NotImplementedError


@repository(UserRepository, name="identity_store")
class MemoryUserRepository(UserRepository):
    def display_name(self, name: str) -> str:
        return name.strip().title()


__all__ = ["MemoryUserRepository", "UserRepository"]
