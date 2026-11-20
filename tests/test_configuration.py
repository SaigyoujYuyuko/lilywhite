"""@configuration 与 @bean 的依赖装配行为测试。"""

from pathlib import Path

import pytest

from lilywhite import bean, configuration
from lilywhite.app.container import DependencyContainer, DependencyInjectionException
from lilywhite.app.runtime import ApplicationRuntime
from lilywhite.config import AppProperties
from lilywhite.utils.configuration import registered_bean_methods


class Engine:
    """记录连接参数的可托管 Bean。"""

    def __init__(self, url: str) -> None:
        self.url = url
        self.initialized = False
        self.closed = False

    async def initialize(self) -> None:
        self.initialized = True

    async def close(self) -> None:
        self.closed = True


class SessionFactory:
    """持有共享引擎的下游 Bean。"""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine


@configuration
class DatabaseConfiguration:
    """用普通同步方法声明一条依赖链。"""

    @bean
    def engine(self) -> Engine:
        return Engine("memory://local")

    @bean()
    def session_factory(self, engine: Engine) -> SessionFactory:
        return SessionFactory(engine)


def register_configuration(container: DependencyContainer, configuration_type: type[object]) -> None:
    """通过公开容器注册接口装配当前测试配置类。"""
    instance = configuration_type()
    for factory in registered_bean_methods(configuration_type):
        container.register_bean(instance, factory)


def test_bean_dependencies_are_singletons_and_managed_components() -> None:
    """工厂参数按类型注入，Bean 复用并进入托管组件列表。"""
    container = DependencyContainer("memory")
    register_configuration(container, DatabaseConfiguration)
    container.build()

    engine = container.resolve(Engine)
    session_factory = container.resolve(SessionFactory)

    assert session_factory.engine is engine
    assert container.resolve(Engine) is engine
    assert engine.url == "memory://local"
    assert list(container.managed_components()) == [engine]


def test_duplicate_bean_return_type_is_rejected() -> None:
    """同一返回类型不能由两个工厂隐式竞争。"""

    @configuration
    class DuplicateConfiguration:
        @bean
        def first_engine(self) -> Engine:
            return Engine("first")

        @bean
        def second_engine(self) -> Engine:
            return Engine("second")

    container = DependencyContainer("memory")
    instance = DuplicateConfiguration()
    container.register_bean(instance, instance.first_engine)

    with pytest.raises(DependencyInjectionException, match="Bean 重复注册"):
        container.register_bean(instance, instance.second_engine)


def test_async_bean_factory_is_rejected_explicitly() -> None:
    """第一版不使用异步工厂或隐式事件循环。"""

    @configuration
    class AsyncConfiguration:
        @bean
        async def engine(self) -> Engine:
            return Engine("async")

    container = DependencyContainer("memory")
    instance = AsyncConfiguration()

    with pytest.raises(DependencyInjectionException, match="必须是同步方法"):
        container.register_bean(instance, instance.engine)


def test_bean_factory_requires_concrete_return_type() -> None:
    """没有返回类型时不能猜测 Bean 的注册契约。"""

    @configuration
    class MissingTypeConfiguration:
        @bean
        def untyped(self):  # noqa: ANN202  # type: ignore[no-untyped-def]
            return Engine("untyped")

    container = DependencyContainer("memory")
    instance = MissingTypeConfiguration()

    with pytest.raises(DependencyInjectionException, match="缺少具体返回类型"):
        container.register_bean(instance, instance.untyped)


def test_configuration_completes_ast_discovery_and_container_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """业务包中的配置类应经真实 AST 扫描进入容器并完成构造。"""
    package = "bean_discovery_app"
    root = tmp_path / package
    root.mkdir()
    (root / "__init__.py").write_text('"""Bean 扫描示例。"""\n', encoding="utf-8")
    (root / "infra.py").write_text(
        "from lilywhite import bean, configuration\n"
        "@configuration\n"
        "class Infrastructure:\n"
        "    @bean\n"
        "    def greeting(self) -> str:\n"
        '        return "春が来た"\n',
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    runtime = ApplicationRuntime(AppProperties(), business_package=package)

    assert runtime.container.resolve(str) == "春が来た"
