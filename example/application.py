"""LilyWhite 问候示例的彩色入口与业务生命周期。"""

from lilywhite import LilywhiteMain
from lilywhite.logger import LoggerManager

log = LoggerManager.get_logger("EXAMPLE")


@LilywhiteMain
class ExampleApplication:
    """声明示例元数据、默认后端和业务生命周期钩子。"""

    application_name = "LilyWhite Greeting Example"
    application_version = "0.2.0"
    backends = ("memory",)

    def banner(self) -> str:
        """用自定义彩色字符画覆盖框架默认 Banner。"""
        return (
            "\033[95m  春が来た！LilyWhite Greeting Example\033[0m\n"
            "\033[96m  Custom banner powered by ExampleApplication\033[0m"
        )

    async def on_startup(self) -> None:
        """在框架组件完成后执行示例业务初始化。"""
        log.info("example startup hook executed; greeting service is ready")

    async def on_shutdown(self) -> None:
        """在框架组件关闭前执行示例业务清理。"""
        log.info("example shutdown hook executed")


__all__ = ["ExampleApplication"]
