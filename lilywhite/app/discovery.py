"""AST 静态模块发现、精确导入与 Controller 收集。"""

import ast
from importlib import import_module
from pathlib import Path
from pkgutil import walk_packages
from types import ModuleType

from litestar import Controller
from litestar.handlers.websocket_handlers import WebsocketListener

from ..controller.registry import registered_controllers
from ..controller.websocket import registered_websocket_controllers
from ..logger import LoggerManager

log = LoggerManager.get_logger("DI")

type BackendSelection = str | tuple[str, ...]

_DECORATOR_SOURCES = {
    "controller": frozenset({"lilywhite", "lilywhite.controller", "lilywhite.controller.registry"}),
    "websocket_controller": frozenset({"lilywhite", "lilywhite.controller.websocket"}),
    "service": frozenset({"lilywhite", "lilywhite.services.registry"}),
    "repository": frozenset({"lilywhite", "lilywhite.storage.registry"}),
    "component": frozenset({"lilywhite", "lilywhite.utils.component"}),
}


class StaticDiscoveryError(ValueError):
    """业务源码无法安全地进行静态发现。"""


def normalize_backends(selection: BackendSelection) -> tuple[str, ...]:
    """规范化单个或多个后端名称，去空、去重并保持声明顺序。"""
    values = (selection,) if isinstance(selection, str) else selection
    normalized = tuple(dict.fromkeys(value.strip() for value in values))
    if not normalized or any(not value for value in normalized):
        raise ValueError("至少启用一个非空存储后端")
    return normalized


def _dotted_name(node: ast.AST) -> str | None:
    """把 Name 和 Attribute 表达式还原为点分名称。"""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        owner = _dotted_name(node.value)
        return None if owner is None else f"{owner}.{node.attr}"
    return None


def _import_aliases(tree: ast.Module) -> tuple[dict[str, str], dict[str, str]]:
    """收集模块级导入中 LilyWhite 装饰器与模块的本地别名。"""
    decorators: dict[str, str] = {}
    modules: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "lilywhite" or alias.name.startswith("lilywhite."):
                    local_name = alias.asname or alias.name.partition(".")[0]
                    modules[local_name] = "lilywhite" if alias.asname is None else alias.name
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            for alias in node.names:
                if alias.name in _DECORATOR_SOURCES and node.module in _DECORATOR_SOURCES[alias.name]:
                    decorators[alias.asname or alias.name] = alias.name
    return decorators, modules


def _decorator_name(
    decorator: ast.expr,
    decorators: dict[str, str],
    modules: dict[str, str],
) -> str | None:
    """识别直接导入和模块属性两种 LilyWhite 装饰器写法。"""
    expression = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(expression, ast.Name):
        return decorators.get(expression.id)

    dotted = _dotted_name(expression)
    if dotted is None:
        return None
    root, separator, attributes = dotted.partition(".")
    module_name = modules.get(root)
    if module_name is None:
        return None
    qualified = f"{module_name}{separator}{attributes}"
    owner, _, name = qualified.rpartition(".")
    if name in _DECORATOR_SOURCES and owner in _DECORATOR_SOURCES[name]:
        return name
    return None


def _repository_backend(decorator: ast.expr, source: Path) -> str:
    """读取 Repository 的静态后端名，动态表达式会在导入前明确报错。"""
    location = f"{source}:{decorator.lineno}"
    if not isinstance(decorator, ast.Call):
        raise StaticDiscoveryError(f"{location} 的 @repository 必须显式声明字符串 backend")
    keyword = next((item for item in decorator.keywords if item.arg == "backend"), None)
    if (
        keyword is None
        or not isinstance(keyword.value, ast.Constant)
        or not isinstance(keyword.value.value, str)
    ):
        raise StaticDiscoveryError(f"{location} 的 @repository backend 必须是字符串字面量")
    backend = keyword.value.value.strip()
    if not backend:
        raise StaticDiscoveryError(f"{location} 的 @repository backend 不能为空")
    return backend


def _module_name(package_name: str, root: Path, source: Path) -> str:
    """把包内文件路径转换为可导入的精确模块名。"""
    relative = source.relative_to(root)
    parts = list(relative.parts)
    if parts[-1] == "__init__.py":
        parts.pop()
    else:
        parts[-1] = source.stem
    return ".".join((package_name, *parts))


def _contains_selected_decorator(tree: ast.Module, source: Path, backends: tuple[str, ...]) -> bool:
    """只检查模块级类，并按启用后端筛选 Repository Adapter。"""
    decorators, modules = _import_aliases(tree)
    selected = False
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for decorator in node.decorator_list:
            name = _decorator_name(decorator, decorators, modules)
            if name is None:
                continue
            if name != "repository" or _repository_backend(decorator, source) in backends:
                selected = True
    return selected


def scan_decorated_modules(
    package_name: str,
    backends: BackendSelection = "memory",
) -> tuple[str, ...]:
    """AST 解析业务包，返回含 LilyWhite 装饰器的排序去重模块列表。"""
    enabled_backends = normalize_backends(backends)
    package = import_module(package_name)
    spec = package.__spec__
    if spec is None or spec.submodule_search_locations is None:
        raise TypeError(f"扫描目标不是包：{package_name}")

    log.debug("static scan start package={} backends={}", package_name, enabled_backends)
    discovered: set[str] = set()
    for location in spec.submodule_search_locations:
        root = Path(location)
        for source in sorted(root.rglob("*.py")):
            try:
                tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            except SyntaxError as error:
                raise StaticDiscoveryError(
                    f"无法解析业务源码 {source}:{error.lineno}：{error.msg}"
                ) from error
            if _contains_selected_decorator(tree, source, enabled_backends):
                module_name = _module_name(package_name, root, source)
                discovered.add(module_name)
                log.trace("static module selected module={}", module_name)

    modules = tuple(sorted(discovered))
    log.debug("static scan complete package={} modules={}", package_name, len(modules))
    return modules


def import_decorated_modules(
    package_name: str,
    backends: BackendSelection = "memory",
) -> list[ModuleType]:
    """只导入静态扫描选中的模块，让原有装饰器完成真实注册。"""
    imported: list[ModuleType] = []
    for module_name in scan_decorated_modules(package_name, backends):
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
            getattr(controller_type, "path", "/"),
        )
    log.debug("controller discovery complete package={} controllers={}", package_name, len(discovered))
    return discovered


def discover_controllers(package_name: str = "lilywhite.controller") -> list[type[Controller]]:
    """递归导入框架 Controller 包并收集显式注册的类型。"""
    import_package_modules(package_name)
    return _sorted_controllers(package_name)


def discover_business_controllers(
    package_name: str,
    backends: BackendSelection,
) -> list[type[Controller]]:
    """静态发现并精确导入业务模块，再收集当前业务包的 Controller。"""
    import_decorated_modules(package_name, backends)
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
            getattr(controller_type, "path", "/"),
        )
    log.debug("websocket discovery complete package={} controllers={}", package_name, len(discovered))
    return discovered
