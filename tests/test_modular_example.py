"""identity、billing、catalog 模块化单体的真实请求和资源关闭测试。"""

from importlib import import_module

from litestar.testing import TestClient

from example.modules.infrastructure import DatabaseEngine, HttpClient
from example.properties import ExampleProperties
from lilywhite import LilyWhiteApplication


def test_modular_monolith_http_calls_and_resource_lifecycle() -> None:
    """billing 经 identity 公开 Service 调用，命名基础设施分别注入并关闭。"""
    framework = LilyWhiteApplication(ExampleProperties(), business_package="example")

    with TestClient(framework.create_app()) as client:
        identity = client.get("/api/v1/modules/identity/users/lily")
        billing = client.get("/api/v1/modules/billing/invoices/lily")
        assert identity.status_code == 200
        assert billing.status_code == 200
        assert identity.json() == {"name": "Lily", "engine": "primary", "client": "identity"}
        assert billing.json() == {"customer": "Lily", "total": 42, "engine": "replica", "client": "billing"}
        assert "catalog_service" not in framework.container.litestar_dependencies()

    primary = framework.container.resolve(DatabaseEngine, "primary")
    replica = framework.container.resolve(DatabaseEngine, "replica")
    identity_client = framework.container.resolve(HttpClient, "identity_http")
    billing_client = framework.container.resolve(HttpClient, "billing_http")
    assert primary.disposed and replica.disposed
    assert identity_client.closed and billing_client.closed


def test_catalog_module_can_be_enabled_without_changing_other_modules() -> None:
    """条件配置启用 catalog 的 Configuration、Service 和 Repository。"""
    properties = ExampleProperties().override(features={"catalog": True})
    framework = LilyWhiteApplication(properties, business_package="example")
    catalog_type = import_module("example.modules.catalog.service").CatalogService

    with TestClient(framework.create_app()) as client:
        greeting = client.get("/api/v1/greetings/Lily")
        catalog = framework.container.resolve(catalog_type)
        assert greeting.status_code == 200
        assert catalog.stickers() == ["春が来た", "Lily White"]
