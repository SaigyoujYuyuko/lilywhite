"""问候Repository的内存实现示例。"""

from ...storage.greeting import GreetingRepository
from ..registry import repository


@repository(GreetingRepository, backend="memory")
class MemoryGreetingRepository:
    """不访问数据库的最小Repository Adapter。"""

    def greeting(self, name: str) -> str:
        """返回可直接用于演示的问候语。"""
        return f"你好，{name}！lilywhite 模板已经运行。"


__all__ = ["MemoryGreetingRepository"]
