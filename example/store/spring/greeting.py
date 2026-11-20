"""由业务配置启用的春季问候 Repository。"""

from lilywhite import enabled, repository

from ...store.greeting import GreetingRepository


@enabled("features.spring_greeting")
@repository(GreetingRepository)
class SpringGreetingRepository:
    """只在 features.spring_greeting=true 时参与依赖绑定。"""

    def greeting(self, name: str) -> str:
        """返回带有东方主题的春季问候。"""
        return f"春が来た，{name}！LilyWhite 与你同在。"


__all__ = ["SpringGreetingRepository"]
