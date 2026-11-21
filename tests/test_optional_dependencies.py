"""静态 enabled 路径在导入前排除未安装的可选第三方依赖。"""

import sys
from pathlib import Path

import pytest
from litestar.testing import TestClient

from lilywhite import AppProperties, LilyWhiteApplication, enabled, service
from lilywhite.app.runtime import ApplicationRuntime
from lilywhite.config import section
from lilywhite.decorators.conditional import condition_enabled


class IntegrationProperties(AppProperties):
    """模拟 MySQL、Redis、Kafka 都未安装的部署环境。"""

    integrations = section(mysql=False, redis=False, kafka=False)


def _optional_source(module: str, decorator: str, condition: str) -> str:
    """生成顶层就依赖不存在第三方包的集成模块。"""
    return (
        f"import {module}\n"
        "import lilywhite as lw\n"
        "from lilywhite import enabled, service\n"
        f"@enabled({condition!r})\n"
        f"@{decorator}\n"
        "class OptionalIntegration:\n"
        "    pass\n"
    )


def test_disabled_integrations_are_not_imported_and_http_still_works(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """禁用 MySQL、Redis、Kafka 时不导入模块，内存业务和真实路由正常。"""
    package = "optional_dependencies_app"
    root = tmp_path / package
    root.mkdir()
    (root / "__init__.py").write_text('"""可选依赖示例。"""\n', encoding="utf-8")
    integrations = {
        "mysql": "missing_lilywhite_mysql_driver",
        "redis": "missing_lilywhite_redis_driver",
        "kafka": "missing_lilywhite_kafka_driver",
    }
    for integration, module in integrations.items():
        (root / f"{integration}.py").write_text(
            _optional_source(module, "lw.service", f"integrations.{integration}"),
            encoding="utf-8",
        )
    (root / "memory.py").write_text(
        "from lilywhite import service\n"
        "@service\n"
        "class MemoryService:\n"
        "    def greeting(self) -> str:\n"
        "        return '春が来た'\n",
        encoding="utf-8",
    )
    (root / "web.py").write_text(
        "from litestar import Controller, get\n"
        "from litestar.di import NamedDependency\n"
        "from lilywhite import controller\n"
        "from .memory import MemoryService\n"
        "@controller('/api')\n"
        "class MemoryController(Controller):\n"
        "    @get('/greeting')\n"
        "    async def greeting(\n"
        "        self, memory_service: NamedDependency[MemoryService]\n"
        "    ) -> dict[str, str]:\n"
        "        return {'message': memory_service.greeting()}\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    framework = LilyWhiteApplication(IntegrationProperties(), business_package=package)

    with TestClient(framework.create_app()) as client:
        response = client.get("/api/greeting")

    assert response.status_code == 200
    assert response.json() == {"message": "春が来た"}
    for integration in integrations:
        assert f"{package}.{integration}" not in sys.modules


def test_enabled_integration_still_requires_its_driver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """配置打开集成后仍按真实导入处理，缺失驱动会直接指出安装需求。"""
    package = "enabled_optional_dependency_app"
    root = tmp_path / package
    root.mkdir()
    (root / "__init__.py").write_text('"""可选依赖启用示例。"""\n', encoding="utf-8")
    (root / "mysql.py").write_text(
        _optional_source("missing_lilywhite_mysql_driver", "service", "integrations.mysql"),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    properties = IntegrationProperties().override(integrations={"mysql": True})

    with pytest.raises(ModuleNotFoundError, match="missing_lilywhite_mysql_driver"):
        ApplicationRuntime(properties, business_package=package)


def test_dynamic_condition_keeps_general_enabled_semantics() -> None:
    """非字面量路径不会参与导入前排除，仍由现有条件注册器计算。"""

    @enabled(lambda _properties: False)
    @service
    class DynamicDisabled:
        pass

    assert not condition_enabled(DynamicDisabled, AppProperties())


def test_membership_lambda_skips_missing_disabled_driver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SQLite/后端成员判断为 False 时，PostgreSQL 驱动不应在导入阶段触发。"""

    class BackendProperties(AppProperties):
        storage = section(enabled_backends=("memory",))

    package = "membership_optional_dependency_app"
    root = tmp_path / package
    root.mkdir()
    (root / "__init__.py").write_text('"""成员条件可选依赖。"""\n', encoding="utf-8")
    (root / "postgres.py").write_text(
        "import missing_lilywhite_postgres_driver\n"
        "from lilywhite import enabled, service\n"
        "@enabled(lambda properties: 'postgres' in properties.storage.enabled_backends)\n"
        "@service\n"
        "class PostgresService:\n"
        "    pass\n",
        encoding="utf-8",
    )
    (root / "memory.py").write_text(
        "from lilywhite import service\n@service\nclass MemoryService:\n    pass\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    ApplicationRuntime(BackendProperties(), business_package=package)

    assert f"{package}.postgres" not in sys.modules
