"""Repository Interface、存储 Adapter 与事务边界契约。"""

from .unit_of_work import TransactionBoundary, TransactionSession, UnitOfWork

__all__ = ["TransactionBoundary", "TransactionSession", "UnitOfWork"]
