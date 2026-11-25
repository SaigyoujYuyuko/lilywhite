"""问候示例的声明式响应后台任务。"""

from lilywhite import background_task
from lilywhite.logger import LoggerManager

log = LoggerManager.get_logger("EXAMPLE")


@background_task
def log_greeting(name: str) -> None:
    """在问候响应发送后记录一条日志，不延长业务响应内容。"""
    log.info("greeting response finished; background task received name={}", name)


__all__ = ["log_greeting"]
