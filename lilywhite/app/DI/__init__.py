"""依赖注入容器、作用域、静态发现与 Controller 收集接口。"""

from .ast_scan import ASTScanner, DecoratedClass, StaticScanError, scan_decorated_classes
from .container import DependencyContainer, DependencyInjectionException, DependencyScope, create_container
from .discovery import (
    discover_business_controllers,
    discover_controllers,
    discover_websocket_controllers,
    import_decorated_modules,
    import_package_modules,
    scan_decorated_modules,
)
from .scope import RequestScopeMiddleware

__all__ = [
    "ASTScanner",
    "DecoratedClass",
    "DependencyContainer",
    "DependencyInjectionException",
    "DependencyScope",
    "RequestScopeMiddleware",
    "StaticScanError",
    "create_container",
    "discover_business_controllers",
    "discover_controllers",
    "discover_websocket_controllers",
    "import_decorated_modules",
    "import_package_modules",
    "scan_decorated_classes",
    "scan_decorated_modules",
]
