"""应用模块发现、多后端条件导入与Controller收集。"""

from importlib import import_module
from pkgutil import walk_packages
from types import ModuleType

from litestar import Controller
from litestar.handlers.websocket_handlers import WebsocketListener

from ..controller.registry import registered_controllers
from ..controller.websocket import registered_websocket_controllers
from ..logger import LoggerManager

log = LoggerManager.get_logger("DI")

type BackendSelection = str | tuple[str, ...]


def normalize_backends(selection: BackendSelection) -> tuple[str, ...]:
    """规范化单个或多个后端名称，去空、去重并保持声明顺序。"""
    values = (selection,) if isinstance(selection, str) else selection
    normalized = tuple(dict.fromkeys(value.strip() for value in values))
    if not normalized or any(not value for value in normalized):
        raise ValueError("至少启用一个非空存储后端")
    return normalized


def import_package_modules(
    package_name: str,
    *,
    exclude_packages: tuple[str, ...] = (),
) -> list[ModuleType]:
    """递归导入包内模块，在导入前跳过明确排除的子包。"""
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


def import_backend_modules(package_name: str, selection: BackendSelection) -> list[ModuleType]:
    """导入全部启用的后端子包，保留公共模块和非Adapter子包。"""
    backends = normalize_backends(selection)
    package = import_module(package_name)
    backend_packages = getattr(package, "backend_packages", ())
    if not isinstance(backend_packages, tuple) or not all(
        isinstance(name, str) and name for name in backend_packages
    ):
        raise TypeError(f"{package_name}.backend_packages 必须是后端子包名称元组")
    unknown = tuple(name for name in backends if name not in backend_packages)
    if backend_packages and unknown:
        raise ValueError(f"存储后端 {unknown} 未在 {package_name}.backend_packages 中声明")
    excluded = tuple(f"{package_name}.{name}" for name in backend_packages if name not in backends)
    log.debug("storage backend scan enabled={} excluded={}", backends, excluded)
    return import_package_modules(package_name, exclude_packages=excluded)


def discover_controllers(package_name: str = "lilywhite.controller") -> list[type[Controller]]:
    """递归导入包并收集显式使用@controller注册的Controller类型。"""
    import_package_modules(package_name)
    discovered = sorted(
        registered_controllers(package_name),
        key=lambda controller_type: (controller_type.__module__, controller_type.__name__),
    )
    for controller_type in discovered:
        log.trace(
            "controller discovered controller={}.{} path={}",
            controller_type.__module__,
            controller_type.__qualname__,
            getattr(controller_type, "path", "/"),
        )
    log.debug("controller discovery complete package={} controllers={}", package_name, len(discovered))
    return discovered


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
            getattr(controller_type, "path", "/"),
        )
    log.debug("websocket discovery complete package={} controllers={}", package_name, len(discovered))
    return discovered
