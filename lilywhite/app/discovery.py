"""LilyWhite 装饰器筛选、精确导入与 Controller 收集。"""

from importlib import import_module
from pkgutil import walk_packages
from types import ModuleType

from litestar import Controller
from litestar.handlers.websocket_handlers import WebsocketListener

from ..decorators.controller import registered_controllers
from ..decorators.websocket import registered_websocket_controllers
from ..logger import LoggerManager
from .ast_scan import StaticScanError, scan_decorated_classes

StaticDiscoveryError = StaticScanError

log = LoggerManager.get_logger("DI")

_DECORATOR_SOURCES = {
    "controller": frozenset({"lilywhite", "lilywhite.decorators.controller"}),
    "websocket_controller": frozenset({"lilywhite", "lilywhite.decorators.websocket"}),
    "service": frozenset({"lilywhite", "lilywhite.decorators.service"}),
    "repository": frozenset({"lilywhite", "lilywhite.decorators.repository"}),
    "component": frozenset({"lilywhite", "lilywhite.decorators.component"}),
    "configuration": frozenset({"lilywhite", "lilywhite.decorators.configuration"}),
}


def scan_decorated_modules(package_name: str) -> tuple[str, ...]:
    """按 LilyWhite 装饰器筛选需要导入的模块，不在扫描阶段执行条件。"""
    log.debug("static scan start package={}", package_name)
    discovered: set[str] = set()
    for item in scan_decorated_classes(package_name, _DECORATOR_SOURCES):
        discovered.add(item.module)
        log.trace("static module selected module={}", item.module)

    modules = tuple(sorted(discovered))
    log.debug("static scan complete package={} modules={}", package_name, len(modules))
    return modules


def import_decorated_modules(package_name: str) -> list[ModuleType]:
    """只导入静态扫描选中的模块，让原有装饰器完成真实注册。"""
    imported: list[ModuleType] = []
    for module_name in scan_decorated_modules(package_name):
        log.trace("module import module={}", module_name)
        imported.append(import_module(module_name))
    return imported


def import_package_modules(
    package_name: str,
    *,
    exclude_packages: tuple[str, ...] = (),
) -> list[ModuleType]:
    """递归导入框架自身的包，在导入前跳过明确排除的子包。"""
    log.debug("package scan start package={}", package_name)
    package = import_module(package_name)
    spec = package.__spec__
    if spec is None or spec.submodule_search_locations is None:
        raise TypeError(f"扫描目标不是包：{package_name}")

    excluded_prefixes = tuple(f"{name}." for name in exclude_packages)
    modules = walk_packages(spec.submodule_search_locations, prefix=f"{package_name}.")
    imported: list[ModuleType] = []
    for module in sorted(modules, key=lambda item: item.name):
        if module.name in exclude_packages or module.name.startswith(excluded_prefixes):
            log.trace("module import skipped module={}", module.name)
            continue
        log.trace("module import module={}", module.name)
        imported.append(import_module(module.name))
    log.debug("package scan complete package={} modules={}", package_name, len(imported))
    return imported


def _sorted_controllers(package_name: str) -> list[type[Controller]]:
    """读取当前包已注册的 Controller 并记录日志。"""
    discovered = sorted(
        registered_controllers(package_name),
        key=lambda controller_type: (controller_type.__module__, controller_type.__name__),
    )
    for controller_type in discovered:
        log.trace(
            "controller discovered controller={}.{} path={}",
            controller_type.__module__,
            controller_type.__qualname__,
            controller_type.path,  # type: ignore[misc]
        )
    log.debug("controller discovery complete package={} controllers={}", package_name, len(discovered))
    return discovered


def discover_controllers(package_name: str = "lilywhite.controller") -> list[type[Controller]]:
    """递归导入框架 Controller 包并收集显式注册的类型。"""
    import_package_modules(package_name)
    return _sorted_controllers(package_name)


def discover_business_controllers(package_name: str) -> list[type[Controller]]:
    """静态发现并精确导入业务模块，再收集当前业务包的 Controller。"""
    import_decorated_modules(package_name)
    return _sorted_controllers(package_name)


def discover_websocket_controllers(package_name: str) -> list[type[WebsocketListener]]:
    """从已经导入的业务包中收集显式注册的 WebSocket Controller。"""
    discovered = sorted(
        registered_websocket_controllers(package_name),
        key=lambda controller_type: (controller_type.__module__, controller_type.__name__),
    )
    for controller_type in discovered:
        log.trace(
            "websocket controller discovered controller={}.{} path={}",
            controller_type.__module__,
            controller_type.__qualname__,
            controller_type.path,
        )
    log.debug("websocket discovery complete package={} controllers={}", package_name, len(discovered))
    return discovered


__all__ = [
    "StaticDiscoveryError",
    "discover_business_controllers",
    "discover_controllers",
    "discover_websocket_controllers",
    "import_decorated_modules",
    "import_package_modules",
    "scan_decorated_modules",
]
