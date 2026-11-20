"""billing 私有 Repository。"""

from lilywhite import repository


class InvoiceRepository:
    def total(self) -> int:
        raise NotImplementedError


@repository(InvoiceRepository, name="billing_store")
class MemoryInvoiceRepository(InvoiceRepository):
    def total(self) -> int:
        return 42


__all__ = ["InvoiceRepository", "MemoryInvoiceRepository"]
