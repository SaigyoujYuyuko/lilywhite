"""按已加载配置决定装饰器目标是否参与装配。"""

from collections.abc import Callable
from types import FunctionType, MethodType

from litestar import Controller
from litestar.handlers.websocket_handlers import WebsocketListener

from ..config import AppProperties
from ..logger import LoggerManager
from ..utils.registry import Registry
from .registry import Condition, ConditionRegistration, QualifiedTarget, qualified_name

log = LoggerManager.get_logger("DI")

condition_registry: Registry[ConditionRegistration] = Registry()


def _target_key(target: object) -> str:
    """取得类、普通函数或绑定方法的注册键，不修改目标对象。"""
    if isinstance(target, type):
        if issubclass(target, Controller | WebsocketListener):
            raise TypeError("@enabled 不支持 Controller 或 WebSocket Controller")
        return qualified_name(target)
    if isinstance(target, FunctionType | MethodType):
        return f"{target.__module__}.{target.__qualname__}"
    raise TypeError("@enabled 只能标记类、函数或绑定方法")


def normalize_condition(source: Condition | str) -> ConditionRegistration:
    """把配置路径或谓词转换为装饰器与统一依赖元数据共用的条件。"""
    if isinstance(source, str):
        path = source.strip()
        if not path or any(not part for part in path.split(".")):
            raise ValueError("启用配置路径不能为空，且每段名称都不能为空")
        return ConditionRegistration(path=path)
    if callable(source):
        return ConditionRegistration(predicate=source)
    raise TypeError("启用条件必须是点分配置路径或谓词")


def enabled[T](source: Condition | str) -> Callable[[T], T]:
    """登记配置路径或谓词条件，并保持原目标及其签名不变。"""
    registration = normalize_condition(source)

    def decorate(target: T) -> T:
        key = _target_key(target)
        registry_key = f"enabled.{key}"
        if condition_registry.get(registry_key) is not None:
            raise ValueError(f"目标已声明启用条件：{key}")
        condition_registry.register("enabled", key, registration)
        return target

    return decorate


def condition_enabled(
    target: type[object] | QualifiedTarget,
    properties: AppProperties,
    *,
    direct: ConditionRegistration | None = None,
) -> bool:
    """计算装饰器或直接元数据条件；同一目标不允许重复声明。"""
    key = _target_key(target)
    registered = condition_registry.get(f"enabled.{key}")
    if direct is not None and registered is not None:
        raise ValueError(f"目标同时声明了 conditional 和 @enabled：{key}")
    condition = direct or registered
    if condition is None:
        return True
    enabled_result = condition.evaluate(properties)
    log.debug("condition evaluated target={} enabled={}", key, enabled_result)
    return enabled_result


__all__ = [
    "Condition",
    "ConditionRegistration",
    "condition_enabled",
    "condition_registry",
    "enabled",
    "normalize_condition",
]
