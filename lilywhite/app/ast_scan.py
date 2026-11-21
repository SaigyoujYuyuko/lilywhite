"""可复用的 AST 装饰器扫描器，不导入被扫描的业务模块。"""

import ast
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

type DecoratorSources = Mapping[str, frozenset[str]]


class StaticScanError(ValueError):
    """源码无法按静态规则解析。"""


@dataclass(frozen=True)
class DecoratedClass:
    """一个模块级类或函数及其命中的装饰器和静态条件表达式。"""

    module: str
    class_name: str
    decorator: str
    node: ast.expr
    source: Path
    condition: ast.expr | None = None


class ASTScanner:
    """按调用方提供的装饰器及其合法导入来源扫描 Python 包。"""

    def __init__(self, sources: DecoratorSources) -> None:
        self._sources = sources

    def scan_package(self, package_name: str) -> tuple[DecoratedClass, ...]:
        """递归解析包内源码，返回所有匹配的模块级类或函数。"""
        discovered: list[DecoratedClass] = []
        for source, module_name in package_module_sources(package_name):
            discovered.extend(self.scan_file(source, module_name))
        return tuple(
            sorted(
                discovered,
                key=lambda item: (item.module, item.class_name, item.decorator),
            )
        )

    def scan_file(self, source: Path, module_name: str) -> tuple[DecoratedClass, ...]:
        """扫描单个文件，不执行其中的类和装饰器。"""
        tree = parse_python_source(source)

        decorators, modules = self._import_aliases(tree, module_name, source.name == "__init__.py")
        discovered: list[DecoratedClass] = []
        for target_node in tree.body:
            if not isinstance(target_node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            condition = (
                self._class_condition(target_node, decorators, modules)
                if isinstance(target_node, ast.ClassDef)
                else None
            )
            for decorator_node in target_node.decorator_list:
                name = self._decorator_name(decorator_node, decorators, modules)
                if name is not None:
                    discovered.append(
                        DecoratedClass(
                            module_name,
                            target_node.name,
                            name,
                            decorator_node,
                            source,
                            condition,
                        )
                    )
        return tuple(discovered)

    def _import_aliases(
        self,
        tree: ast.Module,
        module_name: str,
        is_package: bool,
    ) -> tuple[dict[str, str], dict[str, str]]:
        """收集绝对和相对导入中的装饰器别名与模块别名。"""
        decorators: dict[str, str] = {}
        modules: dict[str, str] = {}
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in self._module_prefixes():
                        if alias.name == prefix or alias.name.startswith(f"{prefix}."):
                            local_name = alias.asname or alias.name.partition(".")[0]
                            modules[local_name] = prefix if alias.asname is None else alias.name
                            break
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                source = self._absolute_import(node, module_name, is_package)
                for alias in node.names:
                    if alias.name in self._sources and source in self._sources[alias.name]:
                        decorators[alias.asname or alias.name] = alias.name
        return decorators, modules

    @staticmethod
    def _absolute_import(node: ast.ImportFrom, module_name: str, is_package: bool) -> str:
        """把相对导入还原成与托管注册表声明一致的绝对模块路径。"""
        if node.level == 0:
            return node.module or ""
        parts = module_name.split(".") if is_package else module_name.split(".")[:-1]
        if node.level > 1:
            parts = parts[: -(node.level - 1)]
        if node.module:
            parts.extend(node.module.split("."))
        return ".".join(parts)

    def _module_prefixes(self) -> set[str]:
        """从装饰器来源推导需要跟踪的顶层模块。"""
        return {
            source.partition(".")[0] for source_group in self._sources.values() for source in source_group
        }

    def _class_condition(
        self,
        class_node: ast.ClassDef,
        decorators: dict[str, str],
        modules: dict[str, str],
    ) -> ast.expr | None:
        """找到类上的 enabled 表达式，但不在 AST 阶段执行它。"""
        for decorator in class_node.decorator_list:
            if self._decorator_name(decorator, decorators, modules) == "enabled":
                return decorator
        return None

    def _decorator_name(
        self,
        decorator: ast.expr,
        decorators: dict[str, str],
        modules: dict[str, str],
    ) -> str | None:
        """识别直接导入和模块属性两种装饰器写法。"""
        expression = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(expression, ast.Name):
            return decorators.get(expression.id)

        dotted = self._dotted_name(expression)
        if dotted is None:
            return None
        root, separator, attributes = dotted.partition(".")
        module_name = modules.get(root)
        if module_name is None:
            return None
        qualified = f"{module_name}{separator}{attributes}"
        owner, _, name = qualified.rpartition(".")
        if name in self._sources and owner in self._sources[name]:
            return name
        return None

    @staticmethod
    def _dotted_name(node: ast.AST) -> str | None:
        """把 Name 和 Attribute 表达式还原为点分名称。"""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            owner = ASTScanner._dotted_name(node.value)
            return None if owner is None else f"{owner}.{node.attr}"
        return None

    @staticmethod
    def _module_name(package_name: str, root: Path, source: Path) -> str:
        """把包内文件路径转换为精确模块名。"""
        relative = source.relative_to(root)
        parts = list(relative.parts)
        if parts[-1] == "__init__.py":
            parts.pop()
        else:
            parts[-1] = source.stem
        return ".".join((package_name, *parts))


def parse_python_source(source: Path) -> ast.Module:
    """解析一个业务源码文件，并统一报告静态语法错误。"""
    try:
        return ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    except SyntaxError as error:
        raise StaticScanError(f"无法解析业务源码 {source}:{error.lineno}：{error.msg}") from error


def package_module_sources(package_name: str) -> tuple[tuple[Path, str], ...]:
    """只枚举包源码和模块名，不导入包内子模块。"""
    package = import_module(package_name)
    spec = package.__spec__
    if spec is None or spec.submodule_search_locations is None:
        raise TypeError(f"扫描目标不是包：{package_name}")
    return tuple(
        (source, ASTScanner._module_name(package_name, root, source))
        for location in spec.submodule_search_locations
        for root in (Path(location),)
        for source in sorted(root.rglob("*.py"))
    )


def scan_decorated_classes(
    package_name: str,
    sources: DecoratorSources,
) -> tuple[DecoratedClass, ...]:
    """以函数形式执行一次通用装饰器扫描。"""
    return ASTScanner(sources).scan_package(package_name)


__all__ = [
    "ASTScanner",
    "DecoratedClass",
    "DecoratorSources",
    "StaticScanError",
    "package_module_sources",
    "parse_python_source",
    "scan_decorated_classes",
]
