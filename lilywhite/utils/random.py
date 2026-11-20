"""安全随机来源，集中账号标识和未来会话令牌的生成。"""

import secrets
from typing import Protocol

from ..decorators.component import component


class RandomSource(Protocol):
    """生成指定字节数的十六进制随机值。"""

    def token_hex(self, byte_count: int) -> str:
        """返回长度为 byte_count 两倍的小写十六进制字符串。"""
        ...


@component(interface=RandomSource)
class SecureRandomSource:
    """使用操作系统安全随机数生成器。"""

    def token_hex(self, byte_count: int) -> str:
        """返回不可预测的随机十六进制字符串。"""
        return secrets.token_hex(byte_count)


__all__ = ["RandomSource", "SecureRandomSource"]
