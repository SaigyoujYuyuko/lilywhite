"""用显式名称区分相同类型的多个依赖。"""

import msgspec


class Qualifier(msgspec.Struct, frozen=True):
    """放在 ``Annotated`` 中，为构造器或 Bean 工厂参数选择命名依赖。"""

    name: str

    def __post_init__(self) -> None:
        """限定名必须非空，且不保留容易误写的首尾空白。"""
        if not isinstance(self.name, str):
            raise TypeError("Qualifier 名称必须是字符串")
        if not self.name or self.name != self.name.strip():
            raise ValueError("Qualifier 名称必须非空且不能包含首尾空白")


def qualifier_name(name: str | None) -> str | None:
    """在注册装饰器入口复用同一套限定名校验。"""
    return None if name is None else Qualifier(name).name


__all__ = ["Qualifier", "qualifier_name"]
