"""应用装配公开接口。"""

from .application import LilyWhiteApplication
from .DI.discovery import discover_controllers
from .boot import LilywhiteMain, run

__all__ = ["LilyWhiteApplication", "LilywhiteMain", "discover_controllers", "run"]
