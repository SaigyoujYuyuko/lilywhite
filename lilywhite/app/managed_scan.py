"""从源码声明自动发现托管注册表，不导入注册表模块。"""

import ast

from ..utils.registry import ManagedRegistry, ManagedRegistrySelection, Named
from .ast_scan import ASTScanner, package_module_sources, parse_python_source


def _argument(call: ast.Call, index: int, name: str) -> ast.expr | None:
    """读取构造调用的位置参数或关键字参数。"""
    if index < len(call.args):
        return call.args[index]
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


class ManagedRegistryScanner(ASTScanner):
    """识别 ManagedRegistry 的字面量赋值声明。"""

    def __init__(self) -> None:
        super().__init__(
            {"ManagedRegistry": frozenset({"lilywhite", "lilywhite.utils.registry"})},
        )

    def scan(self, package_name: str) -> ManagedRegistrySelection:
        """预扫描装饰器和来源参数，动态表达式留给显式注册。"""
        declarations: dict[tuple[str, str], ManagedRegistry[Named | type[object]]] = {}
        for source_path, module_name in package_module_sources(package_name):
            tree = parse_python_source(source_path)
            decorators, modules = self._import_aliases(tree, module_name, source_path.name == "__init__.py")
            for statement in tree.body:
                if not isinstance(statement, ast.Assign | ast.AnnAssign) or not isinstance(
                    statement.value, ast.Call
                ):
                    continue
                call = statement.value
                if self._decorator_name(call, decorators, modules) != "ManagedRegistry":
                    continue
                decorator_node = _argument(call, 0, "decorator")
                source_node = _argument(call, 1, "source")
                if not isinstance(decorator_node, ast.Constant) or not isinstance(decorator_node.value, str):
                    continue
                if isinstance(source_node, ast.Name) and source_node.id == "__name__":
                    source = module_name
                elif isinstance(source_node, ast.Constant) and isinstance(source_node.value, str):
                    source = source_node.value
                else:
                    continue
                key = (decorator_node.value, source)
                declarations[key] = ManagedRegistry(*key)
        return tuple(declarations.values())


def scan_managed_registries(package_name: str) -> ManagedRegistrySelection:
    """以函数形式预扫描包内的托管注册表声明。"""
    return ManagedRegistryScanner().scan(package_name)


__all__ = ["ManagedRegistryScanner", "scan_managed_registries"]
