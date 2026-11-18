"""服务组件健康状态与完整健康结果。"""

import threading
import time
from enum import StrEnum

import msgspec

from .metrics import RequestMetricsResult


class HealthStatusType(StrEnum):
    """服务生命周期健康状态。"""

    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STOPPED = "stopped"


class ComponentHealthResult(msgspec.Struct, frozen=True):
    """单个服务组件的健康状态。"""

    healthy: bool
    detail: str = ""


class HealthSnapshot(msgspec.Struct, frozen=True):
    """HealthCenter 内部状态快照。"""

    status: HealthStatusType
    uptime_seconds: float
    components: dict[str, ComponentHealthResult]


class HealthResult(msgspec.Struct, frozen=True):
    """组件状态和请求指标组成的完整健康结果。"""

    status: HealthStatusType
    uptime_seconds: float
    components: dict[str, ComponentHealthResult]
    requests: RequestMetricsResult


class HealthCenter:
    """聚合生命周期与组件状态，不主动探测具体 Module。"""

    def __init__(self) -> None:
        """创建 STARTING 状态和空组件表。"""
        self._lock = threading.Lock()
        self._status = HealthStatusType.STARTING
        self._started_at: float | None = None
        self._components: dict[str, ComponentHealthResult] = {}

    def start(self) -> None:
        """标记应用启动完成并开始计算运行时间。"""
        with self._lock:
            self._started_at = time.monotonic()
            self._status = HealthStatusType.HEALTHY

    def stop(self) -> None:
        """标记应用已经停止。"""
        with self._lock:
            self._status = HealthStatusType.STOPPED

    def set_component(self, name: str, healthy: bool, detail: str = "") -> None:
        """更新组件健康状态，detail 不包含连接信息或秘密。"""
        with self._lock:
            self._components[name] = ComponentHealthResult(healthy=healthy, detail=detail)

    def clear_component(self, name: str) -> None:
        """移除已经卸载的组件。"""
        with self._lock:
            self._components.pop(name, None)

    def snapshot(self) -> HealthSnapshot:
        """返回一致的生命周期和组件状态副本。"""
        with self._lock:
            status = self._status
            started_at = self._started_at
            components = self._components.copy()

        if status is HealthStatusType.HEALTHY and any(
            not component.healthy for component in components.values()
        ):
            status = HealthStatusType.DEGRADED
        uptime = 0.0 if started_at is None else max(0.0, time.monotonic() - started_at)
        return HealthSnapshot(
            status=status,
            uptime_seconds=round(uptime, 3),
            components=components,
        )
