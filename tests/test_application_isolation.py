"""同进程多应用的全局装饰器注册隔离测试。"""

from importlib import import_module
from pathlib import Path

import pytest

from lilywhite import AppProperties
from lilywhite.app.DI.container import DependencyInjectionException
from lilywhite.app.runtime import ApplicationRuntime


def _write_application(root: Path, package: str, greeting: str) -> None:
    """写入同名类和接口，但使用独立业务包与问候值。"""
    package_root = root / package
    package_root.mkdir()
    (package_root / "__init__.py").write_text('"""多应用隔离包。"""\n', encoding="utf-8")
    (package_root / "logic.py").write_text(
        "from lilywhite import repository, service\n"
        "class Contract:\n"
        "    def greeting(self) -> str:\n"
        "        raise NotImplementedError\n"
        "@repository(Contract)\n"
        "class Adapter(Contract):\n"
        "    def greeting(self) -> str:\n"
        f"        return {greeting!r}\n"
        "@service\n"
        "class AppService:\n"
        "    def __init__(self, repository: Contract) -> None:\n"
        "        self.repository = repository\n",
        encoding="utf-8",
    )


def test_global_registries_do_not_leak_between_applications(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同名注册按包过滤；创建第二个应用不会改变第一个应用的依赖。"""
    first_package = "isolated_application_a"
    second_package = "isolated_application_b"
    _write_application(tmp_path, first_package, "first")
    _write_application(tmp_path, second_package, "second")
    monkeypatch.syspath_prepend(str(tmp_path))
    first = ApplicationRuntime(AppProperties(), business_package=first_package)
    second = ApplicationRuntime(AppProperties(), business_package=second_package)
    first_module = import_module(f"{first_package}.logic")
    second_module = import_module(f"{second_package}.logic")

    assert first.container.resolve(first_module.AppService).repository.greeting() == "first"
    assert second.container.resolve(second_module.AppService).repository.greeting() == "second"
    with pytest.raises(DependencyInjectionException, match="依赖未注册"):
        first.container.resolve(second_module.AppService)
    with pytest.raises(DependencyInjectionException, match="依赖未注册"):
        second.container.resolve(first_module.AppService)
    assert first.health_center is not second.health_center
