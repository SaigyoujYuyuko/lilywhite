"""LilyWhite 示例应用的业务配置类型。"""

from lilywhite import AppProperties
from lilywhite.config import section, setting


class ExampleProperties(AppProperties):
    """在框架配置之上增加问候功能开关。"""

    features = section(
        spring_greeting=setting(False),
    )


__all__ = ["ExampleProperties"]
