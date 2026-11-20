"""问候业务的Repository Interface示例。"""

from typing import Protocol


class GreetingRepository(Protocol):
    """问候数据来源，由配置条件选择具体实现。"""

    def greeting(self, name: str) -> str:
        """生成指定名字的问候语。"""
        ...


__all__ = ["GreetingRepository"]
