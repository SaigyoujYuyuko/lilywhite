"""问候Repository的内存实现示例。"""

from lilywhite import enabled, repository

from ...store.greeting import GreetingRepository


@enabled(lambda config: not config.features.spring_greeting)
@repository(GreetingRepository)
class MemoryGreetingRepository:
    """未启用春季问候时使用的默认内存 Adapter。"""

    def greeting(self, name: str) -> str:
        """返回可直接用于演示的问候语。"""
        return f"你好，{name}！lilywhite 模板已经运行。"


__all__ = ["MemoryGreetingRepository"]
