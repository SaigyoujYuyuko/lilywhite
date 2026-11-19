"""业务源码静态发现与任意目录装配测试。"""

import sys
from pathlib import Path

import pytest
from litestar.testing import TestClient

from lilywhite import LilyWhiteApplication
from lilywhite.app.discovery import StaticDiscoveryError, scan_decorated_modules
from lilywhite.config import AppProperties


def _write_package(tmp_path: Path, package_name: str, files: dict[str, str]) -> None:
    """在临时源码目录创建可被 Python 导入的业务包。"""
    root = tmp_path / package_name
    for relative_path, content in files.items():
        source = root / relative_path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(content, encoding="utf-8")


def test_ast_scan_resolves_aliases_without_importing_business_modules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """静态扫描应识别别名、排序去重，并忽略非 LilyWhite 装饰器。"""
    package = "static_scan_sample"
    _write_package(
        tmp_path,
        package,
        {
            "__init__.py": '"""临时扫描包。"""\n',
            "http/routes.py": (
                'import lilywhite as lw\n@lw.controller("/custom")\nclass Routes:\n    pass\n'
            ),
            "logic/use_case.py": ("from lilywhite import service as s\n@s()\nclass UseCase:\n    pass\n"),
            "store/memory.py": (
                "from lilywhite.storage.registry import repository as repo\n"
                "class Contract:\n"
                "    pass\n"
                '@repo(Contract, backend="memory")\n'
                "class Memory:\n"
                "    pass\n"
            ),
            "store/mysql.py": (
                "from lilywhite import repository\n"
                "class Contract:\n"
                "    pass\n"
                '@repository(Contract, backend="mysql")\n'
                "class MySQL:\n"
                "    pass\n"
            ),
            "nested/__init__.py": (
                "from lilywhite.utils.component import component\n@component\nclass Resource:\n    pass\n"
            ),
            "nested/conditional.py": (
                "from lilywhite import service\nif True:\n    @service\n    class Hidden:\n        pass\n"
            ),
            "other.py": ("def service(target):\n    return target\n@service\nclass Unrelated:\n    pass\n"),
        },
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    modules = scan_decorated_modules(package, backends=("memory",))

    assert modules == (
        f"{package}.http.routes",
        f"{package}.logic.use_case",
        f"{package}.nested",
        f"{package}.store.memory",
    )
    assert f"{package}.http.routes" not in sys.modules
    assert f"{package}.logic.use_case" not in sys.modules


def test_nonstandard_layer_names_complete_real_http_and_di(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """web、logic、store 目录应完成真实请求，未启用后端不导入。"""
    package = "arbitrary_layers_app"
    _write_package(
        tmp_path,
        package,
        {
            "__init__.py": '"""任意分层示例。"""\n',
            "web/__init__.py": '"""HTTP 层。"""\n',
            "web/endpoints.py": (
                "from litestar import Controller, get\n"
                "from litestar.di import NamedDependency\n"
                "from lilywhite import controller\n"
                "from ..logic.greeting import GreetingService\n"
                '@controller("/custom")\n'
                "class GreetingController(Controller):\n"
                '    @get("/greeting")\n'
                "    async def greeting(\n"
                "        self,\n"
                "        greeting_service: NamedDependency[GreetingService],\n"
                "    ) -> dict[str, str]:\n"
                '        return {"message": greeting_service.greet()}\n'
            ),
            "logic/__init__.py": '"""业务层。"""\n',
            "logic/greeting.py": (
                "from lilywhite import service\n"
                "from ..store.contracts import GreetingRepository\n"
                "@service\n"
                "class GreetingService:\n"
                "    def __init__(self, repository: GreetingRepository) -> None:\n"
                "        self.repository = repository\n"
                "    def greet(self) -> str:\n"
                "        return self.repository.greet()\n"
            ),
            "store/__init__.py": '"""存储层。"""\n',
            "store/contracts.py": (
                "from typing import Protocol\n"
                "class GreetingRepository(Protocol):\n"
                "    def greet(self) -> str:\n"
                "        ...\n"
            ),
            "store/memory.py": (
                "from lilywhite import repository\n"
                "from .contracts import GreetingRepository\n"
                '@repository(GreetingRepository, backend="memory")\n'
                "class MemoryGreetingRepository:\n"
                "    def greet(self) -> str:\n"
                '        return "春が来た，Lily"\n'
            ),
            "store/mysql.py": (
                "from lilywhite import repository\n"
                "from .contracts import GreetingRepository\n"
                '@repository(GreetingRepository, backend="mysql")\n'
                "class MySQLGreetingRepository:\n"
                "    def greet(self) -> str:\n"
                '        return "不应启用"\n'
            ),
        },
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    application = LilyWhiteApplication(
        AppProperties(),
        business_package=package,
        application_name="Arbitrary Layers Test",
    ).create_app()

    with TestClient(application) as client:
        response = client.get("/custom/greeting")

    assert response.status_code == 200
    assert response.json() == {"message": "春が来た，Lily"}
    assert f"{package}.store.mysql" not in sys.modules


def test_dynamic_repository_backend_fails_before_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """动态后端无法静态筛选时，应指出源码位置而不是静默误导入。"""
    package = "dynamic_backend_app"
    _write_package(
        tmp_path,
        package,
        {
            "__init__.py": '"""动态后端示例。"""\n',
            "adapter.py": (
                "from lilywhite import repository\n"
                "backend = 'memory'\n"
                "class Contract:\n"
                "    pass\n"
                "@repository(Contract, backend=backend)\n"
                "class Adapter:\n"
                "    pass\n"
            ),
        },
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(StaticDiscoveryError, match=r"adapter.py:5.*backend 必须是字符串字面量"):
        scan_decorated_modules(package)

    assert f"{package}.adapter" not in sys.modules
