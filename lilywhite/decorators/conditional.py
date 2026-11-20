"""按已加载配置决定装饰器目标是否参与装配。"""

from collections.abc import Callable
from types import FunctionType, MethodType
from typing import Any, Protocol

from litestar import Controller
from litestar.handlers.websocket_handlers import WebsocketListener

from ..config import AppProperties
from ..logger import LoggerManager
from ..utils.registry import Registry
from .registry import QualifiedTarget, qualified_name

log = LoggerManager.get_logger("DI")


class Condition(Protocol):
    """接收实际应用配置并返回是否启用的命名谓词。"""

    __name__: str

    def __call__(self, properties: Any, /) -> bool:
        """根据框架或业务配置计算启用状态。"""
        ...


condition_registry: Registry[Condition] = Registry()


def _target_key(target: object) -> str:
    """取得类、普通函数或绑定方法的注册键，不修改目标对象。"""
    if isinstance(target, type):
        if issubclass(target, Controller | WebsocketListener):
            raise TypeError("@enabled 不支持 Controller 或 WebSocket Controller")
        return qualified_name(target)
    if isinstance(target, FunctionType | MethodType):
        return f"{target.__module__}.{target.__qualname__}"
    raise TypeError("@enabled 只能标记类、函数或绑定方法")


def enabled[T](predicate: Condition) -> Callable[[T], T]:
    """登记启用条件，并保持原类或工厂函数及其签名不变。"""

    def decorate(target: T) -> T:
        key = _target_key(target)
        registry_key = f"enabled.{key}"
        if condition_registry.get(registry_key) is not None:
            raise ValueError(f"目标已声明启用条件：{key}")
        condition_registry.register("enabled", key, predicate)
        return target

    return decorate


def condition_enabled(target: type[object] | QualifiedTarget, properties: AppProperties) -> bool:
    """在装配阶段计算条件；未声明条件的目标始终启用。"""
    key = _target_key(target)
    condition = condition_registry.get(f"enabled.{key}")
    if condition is None:
        return True
    enabled_result = condition(properties)
    if not isinstance(enabled_result, bool):
        raise TypeError(f"启用条件必须返回 bool：{key}")
    log.debug("condition evaluated target={} enabled={}", key, enabled_result)
    return enabled_result


__all__ = ["Condition", "condition_enabled", "condition_registry", "enabled"]
