"""禁用模块缺失依赖的 WARNING 兜底与异常边界测试。"""

from pathlib import Path

import pytest

from lilywhite import AppProperties
from lilywhite.app.runtime import ApplicationRuntime


def _write_package(tmp_path: Path, package: str, failure: str) -> str:
    """生成一个只含业务装饰器的可选集成模块。"""
    root = tmp_path / package
    root.mkdir()
    (root / "__init__.py").write_text('"""可选导入测试包。"""\n', encoding="utf-8")
    if failure == "missing":
        failing_line = "import lilywhite_missing_optional_driver\n"
    else:
        failing_line = "raise RuntimeError('adapter initialization bug')\n"
    (root / "integration.py").write_text(
        failing_line + "from lilywhite import service\n@service\nclass IntegrationService:\n    pass\n",
        encoding="utf-8",
    )
    (root / "memory.py").write_text(
        "from lilywhite import service\n@service\nclass MemoryService:\n    pass\n",
        encoding="utf-8",
    )
    return f"{package}.integration"


def test_disabled_prefix_skips_only_module_not_found(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """业务声明为禁用的前缀可跳过缺失驱动并继续装配其他模块。"""
    package = "optional_import_skip_app"
    integration = _write_package(tmp_path, package, "missing")
    monkeypatch.syspath_prepend(str(tmp_path))

    ApplicationRuntime(
        AppProperties(),
        business_package=package,
        optional_imports=(integration,),
    )


def test_enabled_module_missing_dependency_remains_fatal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未声明为可选的启用模块仍原样抛出缺失依赖。"""
    package = "optional_import_fatal_app"
    _write_package(tmp_path, package, "missing")
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(ModuleNotFoundError, match="lilywhite_missing_optional_driver"):
        ApplicationRuntime(AppProperties(), business_package=package)


def test_optional_prefix_does_not_hide_other_exceptions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """即使前缀可选，RuntimeError 等其他异常也必须继续进入全局异常路径。"""
    package = "optional_import_runtime_error_app"
    integration = _write_package(tmp_path, package, "runtime")
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(RuntimeError, match="adapter initialization bug"):
        ApplicationRuntime(
            AppProperties(),
            business_package=package,
            optional_imports=(integration,),
        )
