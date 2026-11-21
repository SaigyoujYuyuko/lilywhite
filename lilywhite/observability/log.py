"""独立运维凭证保护的日志订阅用例。"""

import secrets
from enum import StrEnum

import msgspec

from ..config import AppProperties
from ..decorators.service import service
from .log_stream import LogStream, LogSubscription, LogSubscriptionLimitException


class LogSubscriptionError(StrEnum):
    """日志订阅无法建立时的运维状态。"""

    DISABLED = "log_stream_disabled"
    AUTHENTICATION_REQUIRED = "authentication_required"
    BUSY = "log_stream_busy"


class LogSubscriptionResult(msgspec.Struct, frozen=True):
    """日志订阅或明确的失败状态，不作为通用业务结果模型。"""

    subscription: LogSubscription | None = None
    error: LogSubscriptionError | None = None


@service
class LogService:
    """校验运维 Bearer Token 并创建日志订阅。"""

    def __init__(self, log_stream: LogStream, properties: AppProperties) -> None:
        """保存日志基础设施和独立运维配置。"""
        self._log_stream = log_stream
        self._properties = properties

    def subscribe(self, authorization: str) -> LogSubscriptionResult:
        """认证Authorization并返回订阅，不读取或记录Token内容。"""
        token = self._properties.operations.log_access_token
        if token is None:
            return LogSubscriptionResult(error=LogSubscriptionError.DISABLED)
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(credentials, token):
            return LogSubscriptionResult(error=LogSubscriptionError.AUTHENTICATION_REQUIRED)
        try:
            subscription = self._log_stream.subscribe()
        except LogSubscriptionLimitException:
            return LogSubscriptionResult(error=LogSubscriptionError.BUSY)
        return LogSubscriptionResult(subscription=subscription)


__all__ = ["LogService", "LogSubscriptionError", "LogSubscriptionResult"]
