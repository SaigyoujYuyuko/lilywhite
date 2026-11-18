"""声明式配置分组、覆盖和校验行为测试。"""

from pathlib import Path

import pytest
from msgspec import Meta

from lilywhite.config import AppProperties, Config, ConfigLoader, section, setting, validate


def test_override_returns_independent_config_copy() -> None:
    """覆盖配置不得修改原对象，嵌套分组仍可点号读取。"""
    original = AppProperties()
    changed = original.override(
        server={"host": "0.0.0.0", "port": 9527},
        logging={"level": "DEBUG", "console": False},
    )

    assert original.server.host == "127.0.0.1"
    assert original.server.port == 8000
    assert changed.server.host == "0.0.0.0"
    assert changed.server.port == 9527
    assert changed.logging.level == "DEBUG"
    assert changed.logging.console is False


def test_lambda_validator_applies_to_overridden_value() -> None:
    """自定义配置可以直接用装饰器上的 lambda 校验条件。"""

    @validate("server.port", lambda value: value == 9527)
    class CustomConfig(Config):
        server = section(port=9527)

    assert CustomConfig().server.port == 9527
    with pytest.raises(ValueError, match=r"server\.port"):
        CustomConfig().override(server={"port": 8000})


def test_yaml_loads_nested_sections_and_normalizes_values(tmp_path: Path) -> None:
    """YAML 保持嵌套结构，路径相对配置文件目录解析。"""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
server:
  port: 9527
  cors:
    allow_origins: [" null ", "https://example.com/"]
logging:
  level: debug
  file: logs/app.log
  file_compression: null
operations:
  metrics_window_size: 100
""".strip(),
        encoding="utf-8",
    )

    properties = ConfigLoader(config_path).load()

    assert properties.server.port == 9527
    assert properties.server.cors.allow_origins == ("null", "https://example.com")
    assert properties.logging.level == "DEBUG"
    assert properties.logging.file == (tmp_path / "logs" / "app.log").resolve()
    assert properties.logging.file_compression is None
    assert properties.operations.metrics_window_size == 100


def test_unknown_yaml_field_is_not_silently_accepted(tmp_path: Path) -> None:
    """拼错的配置字段必须给出明确错误。"""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("server:\n  prot: 9527\n", encoding="utf-8")

    with pytest.raises(ValueError, match="未知配置项"):
        ConfigLoader(config_path).load()


def test_meta_range_constraint_applies_to_default_and_override() -> None:
    """Meta 数值范围同时约束字段默认值和覆盖值。"""

    class RangeConfig(Config):
        server = section(port=setting(8000, meta=Meta(ge=1, le=65535)))

    assert RangeConfig().override(server={"port": 9527}).server.port == 9527
    with pytest.raises(ValueError, match="大于或等于"):
        RangeConfig().override(server={"port": 0})

    with pytest.raises(ValueError, match="小于或等于"):
        RangeConfig().override(server={"port": 65536})


def test_meta_pattern_and_length_constraints() -> None:
    """Meta 可以声明字符串正则与最小长度。"""

    class TextConfig(Config):
        logging = section(
            level=setting("INFO", meta=Meta(pattern=r"^(?:INFO|DEBUG)$", min_length=2)),
        )

    assert TextConfig().logging.level == "INFO"
    with pytest.raises(ValueError, match="正则"):
        TextConfig().override(logging={"level": "INFOO"})

    with pytest.raises(ValueError, match="长度"):
        TextConfig().override(logging={"level": "I"})
