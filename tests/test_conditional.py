"""业务配置类型与条件装配的真实容器和 HTTP 行为测试。"""

from importlib import import_module
from pathlib import Path

import pytest
from litestar import Controller
from litestar.handlers.websocket_handlers import WebsocketListener

import lilywhite.app.boot as boot_module
from lilywhite import AppProperties, LilywhiteMain, run
from lilywhite.app.DI.container import DependencyInjectionException
from lilywhite.app.runtime import ApplicationRuntime
from lilywhite.config import ConfigLoader, section
from lilywhite.decorators.conditional import condition_enabled, enabled
from lilywhite.utils.file import AyaFileIO, FileIO


class FeatureProperties(AppProperties):
    """为条件测试增加两个业务开关。"""

    features = section(ai=False, cache=False)


def _write_feature_config(tmp_path: Path) -> Path:
    """写出只启用 AI 功能的业务配置。"""
    path = tmp_path / "config.yaml"
    path.write_text("version: 1\nfeatures:\n  ai: true\n  cache: false\n", encoding="utf-8")
    return path


def _write_business_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, package: str, source: str
) -> None:
    """创建可由 AST 扫描发现的临时业务包。"""
    root = tmp_path / package
    root.mkdir()
    (root / "__init__.py").write_text('"""临时条件装配包。"""\n', encoding="utf-8")
    (root / "features.py").write_text(source, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))


def _properties(*, ai: bool = True, cache: bool = False) -> FeatureProperties:
    """生成当前测试需要的开关组合。"""
    return FeatureProperties().override(features={"ai": ai, "cache": cache})


def test_config_loader_and_entry_use_custom_properties(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """自定义配置类型应保留业务分组，并贯穿真实 run 启动路径。"""
    path = _write_feature_config(tmp_path)
    loaded = ConfigLoader(path).load(FeatureProperties)
    assert type(loaded) is FeatureProperties
    assert loaded.features.ai is True
    assert loaded.features.cache is False

    @LilywhiteMain
    class ConditionalApplication:
        properties_type = FeatureProperties

    captured: dict[str, AppProperties] = {}

    def capture_application(
        _main_type: type[object],
        properties: AppProperties,
        **_kwargs: object,
    ) -> object:
        captured["properties"] = properties
        return object()

    monkeypatch.setattr(boot_module, "_create_application", capture_application)
    monkeypatch.setattr(boot_module.uvicorn, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(boot_module, "shutdown_logging", lambda: None)

    run(ConditionalApplication, ["--config", str(path)])

    assert type(captured["properties"]) is FeatureProperties
    assert captured["properties"].features.ai is True


def test_conditional_beans_services_and_repositories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """配置组、单个 Bean、Service 和 Repository 应按同一份业务配置启停。"""
    package = "conditional_registrations_app"
    _write_business_package(
        tmp_path,
        monkeypatch,
        package,
        "from lilywhite import bean, configuration, enabled, repository, service\n"
        "class EnabledBean:\n    pass\n"
        "class DisabledBean:\n    pass\n"
        "class DisabledGroupBean:\n    pass\n"
        "class DisabledService:\n    pass\n"
        "class Contract:\n    pass\n"
        "@configuration\n"
        "class FeatureConfiguration:\n"
        "    @bean\n"
        "    @enabled('features.ai')\n"
        "    def enabled_bean(self) -> EnabledBean:\n"
        "        return EnabledBean()\n"
        "    @enabled(lambda config: config.features.cache)\n"
        "    @bean\n"
        "    def disabled_bean(self) -> DisabledBean:\n"
        "        return DisabledBean()\n"
        "@enabled(lambda config: config.features.cache)\n"
        "@configuration\n"
        "class DisabledConfiguration:\n"
        "    def __init__(self) -> None:\n"
        "        raise RuntimeError('禁用配置组不应实例化')\n"
        "    @bean\n"
        "    def disabled_group_bean(self) -> DisabledGroupBean:\n"
        "        return DisabledGroupBean()\n"
        "@service\n"
        "@enabled(lambda config: config.features.cache)\n"
        "class DisabledService:\n    pass\n"
        "@repository(Contract)\n"
        "@enabled(lambda config: config.features.cache)\n"
        "class DisabledRepository:\n    pass\n"
        "@repository(Contract)\n"
        "@enabled('features.ai')\n"
        "class EnabledRepository:\n    pass\n",
    )

    runtime = ApplicationRuntime(_properties(), business_package=package)
    container = runtime.container
    module = import_module(f"{package}.features")

    assert type(container.resolve(module.EnabledBean)).__name__ == "EnabledBean"
    assert type(container.resolve(module.Contract)).__name__ == "EnabledRepository"
    for target in (module.DisabledBean, module.DisabledGroupBean, module.DisabledService):
        with pytest.raises(DependencyInjectionException, match="依赖未注册"):
            container.resolve(target)
    assert "disabled_service" not in container.litestar_dependencies()


def test_disabled_custom_component_allows_builtin_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """业务文件组件禁用后由内置实现补位，启用时仍优先使用业务实现。"""
    package = "conditional_file_component_app"
    _write_business_package(
        tmp_path,
        monkeypatch,
        package,
        "from lilywhite import AyaFileIO, FileIO, component, enabled\n"
        "@component(interface=FileIO)\n"
        "@enabled(lambda config: config.features.cache)\n"
        "class CustomFileIO(AyaFileIO):\n    pass\n",
    )

    disabled_runtime = ApplicationRuntime(_properties(cache=False), business_package=package)
    enabled_runtime = ApplicationRuntime(_properties(cache=True), business_package=package)

    assert type(disabled_runtime.container.resolve(FileIO)) is AyaFileIO
    assert type(enabled_runtime.container.resolve(FileIO)).__name__ == "CustomFileIO"


def test_condition_must_return_bool() -> None:
    """条件返回非 bool 时应在装配阶段明确失败。"""

    @enabled(lambda _config: "yes")
    class InvalidConditionTarget:
        pass

    with pytest.raises(TypeError, match="返回 bool"):
        condition_enabled(InvalidConditionTarget, AppProperties())


def test_condition_rejects_http_and_websocket_controllers() -> None:
    """Controller 不属于条件装配范围，误用装饰器时应直接报错。"""
    with pytest.raises(TypeError, match="不支持 Controller"):

        @enabled(lambda _config: True)
        class ConditionalHttpController(Controller):
            pass

    with pytest.raises(TypeError, match="不支持 Controller"):

        @enabled(lambda _config: True)
        class ConditionalWebsocket(WebsocketListener):
            pass


def test_condition_path_rejects_missing_and_non_boolean_values() -> None:
    """路径条件必须存在并指向 bool，空路径应在声明时拒绝。"""

    class TextFeatureProperties(AppProperties):
        features = section(name="Lily")

    @enabled("features.name")
    class NonBooleanTarget:
        pass

    with pytest.raises(TypeError, match=r"features\.name"):
        condition_enabled(NonBooleanTarget, TextFeatureProperties())

    @enabled("features.missing")
    class MissingPathTarget:
        pass

    with pytest.raises(ValueError, match=r"features\.missing"):
        condition_enabled(MissingPathTarget, FeatureProperties())

    with pytest.raises(ValueError, match="配置路径"):

        @enabled("")
        class EmptyPathTarget:
            pass
