"""托管注册表驱动业务函数装饰器的静态发现测试。"""

import sys
from importlib import import_module
from pathlib import Path

import pytest

from lilywhite import AppProperties
from lilywhite.app.boot import _create_application


def test_managed_registry_discovers_module_level_function_decorators(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """只有自定义 @game_api 的模块也应被精确导入，不需要启动钩子。"""
    package = "managed_registry_app"
    root = tmp_path / package
    root.mkdir()
    (root / "__init__.py").write_text('"""托管注册表示例。"""\n', encoding="utf-8")
    (root / "registry.py").write_text(
        "from lilywhite import ManagedRegistry\n"
        "commands = ManagedRegistry('game_api', __name__)\n"
        "def game_api(target):\n"
        "    commands.register('command', target.__name__, target)\n"
        "    return target\n",
        encoding="utf-8",
    )
    (root / "handlers.py").write_text(
        "from .registry import game_api\n"
        "@game_api\n"
        "def hello() -> str:\n"
        "    return '春が来た'\n"
        "@game_api\n"
        "async def async_hello() -> str:\n"
        "    return 'Lily White'\n",
        encoding="utf-8",
    )
    (root / "application.py").write_text(
        "from lilywhite import LilywhiteMain\n"
        "from .registry import commands\n"
        "@LilywhiteMain\n"
        "class ManagedApplication:\n"
        "    managed_registries = (commands,)\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    module = import_module(f"{package}.application")
    registry_module = import_module(f"{package}.registry")

    assert f"{package}.handlers" not in sys.modules
    _create_application(module.ManagedApplication, AppProperties(), entry=module.ManagedApplication())

    assert f"{package}.handlers" in sys.modules
    assert registry_module.commands.get("command.hello")() == "春が来た"
    assert registry_module.commands.get("command.async_hello") is not None
