"""LilyWhite 装饰器筛选、静态条件排除、精确导入与 Controller 收集。"""

import ast
from collections import defaultdict
from dataclasses import dataclass
from importlib import import_module
from pkgutil import walk_packages
from types import ModuleType

from litestar import Controller
from litestar.handlers.websocket_handlers import WebsocketListener

from ...config import AppProperties
from ...decorators.conditional import ConditionRegistration
from ...decorators.controller import registered_controllers
from ...decorators.websocket import registered_websocket_controllers
from ...logger import LoggerManager
from ...utils.registry import ManagedRegistrySelection
from .ast_scan import DecoratedClass, StaticScanError, scan_decorated_classes
from .managed_scan import scan_managed_registries

StaticDiscoveryError = StaticScanError

log = LoggerManager.get_logger("DI")

_DECORATOR_SOURCES = {
    "background_task": frozenset({"lilywhite", "lilywhite.decorators.background"}),
    "controller": frozenset({"lilywhite", "lilywhite.decorators.controller"}),
    "exception_handler": frozenset({"lilywhite", "lilywhite.decorators.exception_handler"}),
    "middleware": frozenset({"lilywhite", "lilywhite.decorators.middleware"}),
    "websocket_controller": frozenset({"lilywhite", "lilywhite.decorators.websocket"}),
    "service": frozenset({"lilywhite", "lilywhite.decorators.service"}),
    "repository": frozenset({"lilywhite", "lilywhite.decorators.repository"}),
    "component": frozenset({"lilywhite", "lilywhite.decorators.component"}),
    "configuration": frozenset({"lilywhite", "lilywhite.decorators.configuration"}),
    "enabled": frozenset({"lilywhite", "lilywhite.decorators.conditional"}),
}
_CONDITIONAL_DECORATORS = frozenset({"service", "repository", "component", "configuration"})


def _static_condition_path(item: DecoratedClass) -> str | None:
    """提取字面量配置路径；其他动态条件仍需真实导入后计算。"""
    condition = item.condition
    if not isinstance(condition, ast.Constant):
        return None
    return condition.value if isinstance(condition.value, str) else None


def _attribute_path(expression: ast.expr, root: str) -> str | None:
    """把 properties.storage.enabled_backends 还原为点分配置路径。"""
    parts: list[str] = []
    current = expression
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name) or current.id != root or not parts:
        return None
    return ".".join(reversed(parts))


def _static_membership_condition(item: DecoratedClass, properties: AppProperties) -> bool | None:
    """安全计算常量 in/not in 配置集合的简单 lambda，不执行任意表达式。"""
    function = item.condition
    if not isinstance(function, ast.Lambda):
        return None
    if len(function.args.args) != 1 or not isinstance(function.body, ast.Compare):
        return None
    comparison = function.body
    if (
        len(comparison.ops) != 1
        or not isinstance(comparison.ops[0], ast.In | ast.NotIn)
        or len(comparison.comparators) != 1
        or not isinstance(comparison.left, ast.Constant)
    ):
        return None
    path = _attribute_path(comparison.comparators[0], function.args.args[0].arg)
    if path is None:
        return None
    try:
        values = properties._read_path(path)
    except (KeyError, AttributeError, ValueError) as error:
        raise ValueError(f"启用条件的配置路径不存在：{path}") from error
    result = comparison.left.value in values
    return not result if isinstance(comparison.ops[0], ast.NotIn) else result


def _statically_disabled(item: DecoratedClass, properties: AppProperties) -> bool:
    """在导入前排除明确关闭的集成模块，不推测任意 Python 条件。"""
    if item.decorator not in _CONDITIONAL_DECORATORS:
        return False
    membership = _static_membership_condition(item, properties)
    if membership is not None:
        return not membership
    path = _static_condition_path(item)
    if path is None:
        return False
    return not ConditionRegistration(path=path).evaluate(properties)


def _sources_with_managed_registries(
    managed_registries: ManagedRegistrySelection,
) -> dict[str, frozenset[str]]:
    """把入口显式声明的业务注册表并入框架装饰器来源。"""
    sources = dict(_DECORATOR_SOURCES)
    for registry in managed_registries:
        sources[registry.decorator_name] = sources.get(registry.decorator_name, frozenset()).union(
            (registry.source,)
        )
        log.trace(
            "managed registry selected decorator={} source={}",
            registry.decorator_name,
            registry.source,
        )
    return sources


def scan_decorated_modules(
    package_name: str,
    *,
    properties: AppProperties | None = None,
    managed_registries: ManagedRegistrySelection = (),
) -> tuple[str, ...]:
    """筛选框架与托管注册表装饰器；静态条件全关时跳过模块。"""
    log.debug("static scan start package={}", package_name)
    grouped: dict[str, list[DecoratedClass]] = defaultdict(list)
    declared_registries = (*scan_managed_registries(package_name), *managed_registries)
    sources = _sources_with_managed_registries(declared_registries)
    for item in scan_decorated_classes(package_name, sources):
        if item.decorator != "enabled":
            grouped[item.module].append(item)

    discovered: list[str] = []
    for module, items in sorted(grouped.items()):
        if properties is not None and all(_statically_disabled(item, properties) for item in items):
            log.debug("static module skipped by enabled path module={}", module)
            continue
        discovered.append(module)
        log.trace("static module selected module={}", module)

    modules = tuple(discovered)
    log.debug("static scan complete package={} modules={}", package_name, len(modules))
    return modules


@dataclass
class BusinessDiscovery:
    """保存单个应用的业务模块选择结果，并保证精确导入只执行一次。"""

    package_name: str
    module_names: tuple[str, ...]
    _imported: bool = False

    def import_modules(self, optional_imports: tuple[str, ...] = ()) -> None:
        """首次调用执行精确导入，后续容器和 HTTP 装配直接复用结果。"""
        if self._imported:
            return
        import_decorated_modules(
            self.package_name,
            module_names=self.module_names,
            optional_imports=optional_imports,
        )
        self._imported = True


def discover_business_modules(
    package_name: str,
    *,
    properties: AppProperties | None = None,
    managed_registries: ManagedRegistrySelection = (),
) -> BusinessDiscovery:
    """只扫描一次业务包，把结果保存在当前应用的发现对象中。"""
    return BusinessDiscovery(
        package_name,
        scan_decorated_modules(
            package_name,
            properties=properties,
            managed_registries=managed_registries,
        ),
    )


def import_decorated_modules(
    package_name: str,
    *,
    properties: AppProperties | None = None,
    managed_registries: ManagedRegistrySelection = (),
    optional_imports: tuple[str, ...] = (),
    module_names: tuple[str, ...] | None = None,
) -> list[ModuleType]:
    """导入选中模块；仅未启用前缀允许跳过缺失依赖。"""
    selected = (
        scan_decorated_modules(
            package_name,
            properties=properties,
            managed_registries=managed_registries,
        )
        if module_names is None
        else module_names
    )
    imported: list[ModuleType] = []
    for module_name in selected:
        log.trace("module import module={}", module_name)
        try:
            imported.append(import_module(module_name))
        except ModuleNotFoundError as error:
            optional = any(
                module_name == prefix or module_name.startswith(f"{prefix}.") for prefix in optional_imports
            )
            if not optional:
                raise
            log.warning(
                "disabled module skipped because dependency is unavailable module={} missing={}",
                module_name,
                error.name or "unknown",
            )
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


def discover_controllers(package_name: str = "lilywhite.http") -> list[type[Controller]]:
    """递归导入框架 Controller 包并收集显式注册的类型。"""
    import_package_modules(package_name)
    return _sorted_controllers(package_name)


def discover_business_controllers(
    package_name: str,
    *,
    properties: AppProperties | None = None,
    managed_registries: ManagedRegistrySelection = (),
    optional_imports: tuple[str, ...] = (),
    discovery: BusinessDiscovery | None = None,
) -> list[type[Controller]]:
    """复用当前应用的业务发现结果，再按稳定顺序收集 Controller。"""
    if discovery is None:
        discovery = discover_business_modules(
            package_name,
            properties=properties,
            managed_registries=managed_registries,
        )
    elif discovery.package_name != package_name:
        raise ValueError("业务发现结果与 Controller 包不一致")
    discovery.import_modules(optional_imports)
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
    "BusinessDiscovery",
    "StaticDiscoveryError",
    "discover_business_controllers",
    "discover_business_modules",
    "discover_controllers",
    "discover_websocket_controllers",
    "import_decorated_modules",
    "import_package_modules",
    "scan_decorated_modules",
]
