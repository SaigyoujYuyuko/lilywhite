"""identity 模块只公开 Service，Repository 不向外泄漏。"""

from .service import IdentityService

__all__ = ["IdentityService"]
