"""环境变量密钥引用、校验错误和配置模板脱敏测试。"""

import pytest

from lilywhite import AppProperties, env
from lilywhite.cli.config import default_config
from lilywhite.config import ConfigSection, section, setting


class SecretProperties(AppProperties):
    """带环境变量密钥的业务配置。"""

    database = section(url=setting(env("LILYWHITE_TEST_DATABASE_URL"), value_type=str))
    optional = section(
        token=setting(env("LILYWHITE_TEST_OPTIONAL_TOKEN", required=False), value_type=str | None)
    )


def test_secret_ref_resolves_environment_without_exposing_value_in_representation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """运行配置读取真实值，SecretRef 字符串仍只保留变量名。"""
    monkeypatch.setenv("LILYWHITE_TEST_DATABASE_URL", "postgresql://user:password@localhost/app")
    properties = SecretProperties()

    assert properties.database.url == "postgresql://user:password@localhost/app"
    assert "password" not in str(env("LILYWHITE_TEST_DATABASE_URL"))


def test_yaml_environment_reference_is_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    """YAML 中的 ${ENV_NAME} 也在类型校验前解析。"""
    monkeypatch.setenv("LILYWHITE_TEST_API_TOKEN", "test-api-token")
    values = ConfigSection(token=setting(None, value_type=str | None))

    values._update({"token": "${LILYWHITE_TEST_API_TOKEN}"}, None)

    assert values.token == "test-api-token"


def test_missing_required_secret_reports_only_environment_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """缺失密钥的错误不包含连接串或其他配置值。"""
    monkeypatch.delenv("LILYWHITE_TEST_DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="LILYWHITE_TEST_DATABASE_URL"):
        SecretProperties()


def test_optional_secret_can_be_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """非必需环境变量未设置时返回 None。"""
    monkeypatch.setenv("LILYWHITE_TEST_DATABASE_URL", "postgresql://localhost/app")
    monkeypatch.delenv("LILYWHITE_TEST_OPTIONAL_TOKEN", raising=False)
    properties = SecretProperties()
    assert properties.optional.token is None


def test_config_template_preserves_reference_without_reading_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模板生成不解析环境变量，也不会把本机密钥写进 YAML 映射。"""
    monkeypatch.setenv("LILYWHITE_TEST_DATABASE_URL", "postgresql://user:password@localhost/app")

    generated = default_config(SecretProperties)

    assert generated["database"] == {"url": "${LILYWHITE_TEST_DATABASE_URL}"}
    assert "password" not in str(generated)
    assert generated["optional"] == {"token": "${LILYWHITE_TEST_OPTIONAL_TOKEN}"}
