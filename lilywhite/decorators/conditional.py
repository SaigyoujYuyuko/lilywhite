"""按已加载配置决定装饰器目标是否参与装配。"""

from collections.abc import Callable
from types import FunctionType, MethodType
from typing import Any, Protocol

import msgspec
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


class ConditionRegistration(msgspec.Struct, frozen=True):
    """统一保存点分配置路径或自定义谓词。"""

    predicate: Condition | None = None
    path: str | None = None

    @property
    def __name__(self) -> str:
        """让通用 Registry 把条件记录视为命名对象。"""
        if self.path is not None:
            return self.path
        if self.predicate is not None:
            return self.predicate.__name__
        raise RuntimeError("条件必须包含配置路径或谓词")

    def evaluate(self, properties: AppProperties) -> bool:
        """从当前配置计算布尔启用状态，并给出具体失败原因。"""
        if self.path is not None:
            try:
                result = properties._read_path(self.path)
            except (KeyError, AttributeError, ValueError) as error:
                raise ValueError(f"启用条件的配置路径不存在：{self.path}") from error
        elif self.predicate is not None:
            result = self.predicate(properties)
        else:
            raise RuntimeError("条件必须包含配置路径或谓词")
        if not isinstance(result, bool):
            raise TypeError(f"启用条件必须返回 bool：{self.__name__}")
        return result


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


def enabled[T](source: Condition | str) -> Callable[[T], T]:
    """登记配置路径或谓词条件，并保持原目标及其签名不变。"""
    if isinstance(source, str):
        path = source.strip()
        if not path or any(not part for part in path.split(".")):
            raise ValueError("@enabled 配置路径不能为空，且每段名称都不能为空")
        registration = ConditionRegistration(path=path)
    elif callable(source):
        registration = ConditionRegistration(predicate=source)
    else:
        raise TypeError("@enabled 参数必须是点分配置路径或谓词")

    def decorate(target: T) -> T:
        key = _target_key(target)
        registry_key = f"enabled.{key}"
        if condition_registry.get(registry_key) is not None:
            raise ValueError(f"目标已声明启用条件：{key}")
        condition_registry.register("enabled", key, registration)
        return target

    return decorate


def condition_enabled(target: type[object] | QualifiedTarget, properties: AppProperties) -> bool:
    """在装配阶段计算条件；未声明条件的目标始终启用。"""
    key = _target_key(target)
    condition = condition_registry.get(f"enabled.{key}")
    if condition is None:
        return True
    enabled_result = condition.evaluate(properties)
    log.debug("condition evaluated target={} enabled={}", key, enabled_result)
    return enabled_result


__all__ = ["Condition", "ConditionRegistration", "condition_enabled", "condition_registry", "enabled"]
