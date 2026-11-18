"""独立运维凭证保护的日志订阅用例。"""

import secrets

from ..config import AppProperties
from ..observability import LogStream, LogSubscription, LogSubscriptionLimitException
from .registry import service
from .result import ServiceResult, success


@service
class LogService:
    """校验运维 Bearer Token 并创建日志订阅。"""

    def __init__(self, log_stream: LogStream, properties: AppProperties) -> None:
        """保存日志基础设施和独立运维配置。"""
        self._log_stream = log_stream
        self._properties = properties

    def subscribe(self, authorization: str) -> ServiceResult[LogSubscription]:
        """认证Authorization并返回订阅，不读取或记录Token内容。"""
        token = self._properties.operations.log_access_token
        if token is None:
            return ServiceResult.failure("log_stream_disabled", "Log stream is not configured.")
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(credentials, token):
            return ServiceResult.failure("authentication_required", "Authentication required.")
        try:
            subscription = self._log_stream.subscribe()
        except LogSubscriptionLimitException:
            return ServiceResult.failure("log_stream_busy", "Too many active log subscriptions.")
        return success(subscription)


__all__ = ["LogService"]
