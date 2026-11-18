"""Service 统一业务结果与错误模型。"""

from enum import StrEnum

import msgspec


class ServiceStatusType(StrEnum):
    """Service 用例执行状态。"""

    SUCCESS = "success"
    FAILURE = "failure"


class ServiceErrorResult(msgspec.Struct, frozen=True):
    """供 Controller 映射的稳定业务错误。"""

    code: str
    message: str


class ServiceResult[T](msgspec.Struct, frozen=True):
    """携带业务数据或业务错误的用例结果。"""

    status: ServiceStatusType
    data: T | None = None
    error: ServiceErrorResult | None = None

    @classmethod
    def failure(cls, code: str, message: str) -> ServiceResult[T]:
        """构造携带稳定业务错误码的失败结果。"""
        return cls(
            status=ServiceStatusType.FAILURE,
            error=ServiceErrorResult(code=code, message=message),
        )


def success[T](data: T) -> ServiceResult[T]:
    """构造携带业务数据的成功结果。"""
    return ServiceResult(status=ServiceStatusType.SUCCESS, data=data)


__all__ = ["ServiceErrorResult", "ServiceResult", "ServiceStatusType", "success"]
