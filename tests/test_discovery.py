"""业务源码静态发现与任意目录装配测试。"""

import sys
from pathlib import Path

import pytest
from litestar.testing import TestClient

import lilywhite.app.DI.discovery as discovery_module
from lilywhite import LilyWhiteApplication
from lilywhite.app.DI.ast_scan import scan_decorated_classes
from lilywhite.app.DI.discovery import scan_decorated_modules
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
                "from lilywhite.decorators.repository import repository as repo\n"
                "class Contract:\n"
                "    pass\n"
                "@repo(Contract)\n"
                "class Memory:\n"
                "    pass\n"
            ),
            "store/mysql.py": (
                "from lilywhite import repository\n"
                "class Contract:\n"
                "    pass\n"
                "@repository(Contract)\n"
                "class MySQL:\n"
                "    pass\n"
            ),
            "nested/__init__.py": (
                "from lilywhite.decorators.component import component\n@component\nclass Resource:\n    pass\n"
            ),
            "nested/conditional.py": (
                "from lilywhite import service\nif True:\n    @service\n    class Hidden:\n        pass\n"
            ),
            "infra/configuration.py": (
                "from lilywhite import bean, configuration\n"
                "@configuration\n"
                "class Infrastructure:\n"
                "    @bean\n"
                "    def engine(self) -> str:\n"
                '        return "memory"\n'
            ),
            "other.py": ("def service(target):\n    return target\n@service\nclass Unrelated:\n    pass\n"),
        },
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    modules = scan_decorated_modules(package)

    assert modules == (
        f"{package}.http.routes",
        f"{package}.infra.configuration",
        f"{package}.logic.use_case",
        f"{package}.nested",
        f"{package}.store.memory",
        f"{package}.store.mysql",
    )
    assert f"{package}.http.routes" not in sys.modules
    assert f"{package}.logic.use_case" not in sys.modules


def test_generic_ast_scanner_accepts_custom_decorator_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """通用扫描器应能识别任意框架的直接导入和模块别名装饰器。"""
    package = "generic_ast_app"
    _write_package(
        tmp_path,
        package,
        {
            "__init__.py": '"""通用扫描示例。"""\n',
            "components.py": (
                "import imaginary_framework as imf\n"
                "from imaginary_framework import service as s\n"
                "@s()\n"
                "class First:\n"
                "    pass\n"
                "@imf.service\n"
                "class Second:\n"
                "    pass\n"
            ),
        },
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    discovered = scan_decorated_classes(package, {"service": frozenset({"imaginary_framework"})})

    assert [(item.class_name, item.decorator) for item in discovered] == [
        ("First", "service"),
        ("Second", "service"),
    ]
    assert all(item.module == f"{package}.components" for item in discovered)


def test_nonstandard_layer_names_complete_real_http_and_di(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """web、logic、store 目录应完成真实请求，禁用 Repository 不参与绑定。"""
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
                "@repository(GreetingRepository)\n"
                "class MemoryGreetingRepository:\n"
                "    def greet(self) -> str:\n"
                '        return "春が来た，Lily"\n'
            ),
            "store/mysql.py": (
                "from lilywhite import enabled, repository\n"
                "from .contracts import GreetingRepository\n"
                "@enabled(lambda _config: False)\n"
                "@repository(GreetingRepository)\n"
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
    assert f"{package}.store.mysql" in sys.modules


def test_application_reuses_one_business_scan_for_di_and_http(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """容器与多次 HTTP 装配应共享当前 Runtime 的同一份业务发现结果。"""
    package = "single_scan_application"
    _write_package(
        tmp_path,
        package,
        {
            "__init__.py": '"""单次扫描应用。"""\n',
            "routes.py": (
                "from litestar import Controller, get\n"
                "from lilywhite import controller\n"
                '@controller("/once")\n'
                "class OnceController(Controller):\n"
                '    @get("/greeting")\n'
                "    async def greeting(self) -> dict[str, str]:\n"
                '        return {"message": "春が来た"}\n'
            ),
        },
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    scan_calls = 0
    original_scan = discovery_module.scan_decorated_modules

    def counted_scan(package_name: str, **kwargs: object) -> tuple[str, ...]:
        nonlocal scan_calls
        scan_calls += 1
        return original_scan(package_name, **kwargs)

    monkeypatch.setattr(discovery_module, "scan_decorated_modules", counted_scan)
    framework = LilyWhiteApplication(AppProperties(), business_package=package)
    application = framework.create_app()
    framework.create_app()

    with TestClient(application) as client:
        response = client.get("/once/greeting")

    assert response.status_code == 200
    assert response.json() == {"message": "春が来た"}
    assert scan_calls == 1
