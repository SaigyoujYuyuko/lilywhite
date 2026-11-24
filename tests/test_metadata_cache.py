"""构造器元数据缓存的调用次数、限定名和容器隔离测试。"""

from typing import Annotated

import pytest

import lilywhite.app.container as container_module
from lilywhite import Qualifier
from lilywhite.app.container import DependencyContainer
from lilywhite.utils.registry import LifetimeType


class CacheLeaf:
    """缓存测试叶节点。"""


class CacheRoot:
    """带有限定名的构造器依赖。"""

    def __init__(self, leaf: Annotated[CacheLeaf, Qualifier("current")]) -> None:
        self.leaf = leaf


def test_constructor_metadata_is_read_once_per_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """图校验后多次 Scoped 解析不再重复 signature 和 get_type_hints。"""
    signature_calls = 0
    hints_calls = 0
    original_signature = container_module.signature
    original_hints = container_module.get_type_hints

    def counted_signature(target: object) -> object:
        nonlocal signature_calls
        signature_calls += 1
        return original_signature(target)

    def counted_hints(target: object, *, include_extras: bool) -> dict[str, object]:
        nonlocal hints_calls
        hints_calls += 1
        return original_hints(target, include_extras=include_extras)

    monkeypatch.setattr(container_module, "signature", counted_signature)
    monkeypatch.setattr(container_module, "get_type_hints", counted_hints)
    container = DependencyContainer()
    container.register_component(CacheLeaf, CacheLeaf, LifetimeType.SCOPED, name="current")
    container.register_service(CacheRoot, LifetimeType.SCOPED)
    container.build()
    assert signature_calls == 1
    assert hints_calls == 1

    first = container.create_scope().resolve(CacheRoot)
    second = container.create_scope().resolve(CacheRoot)
    assert first is not second
    assert first.leaf is not second.leaf
    assert signature_calls == 1
    assert hints_calls == 1


def test_metadata_cache_is_not_shared_between_containers() -> None:
    """新容器独立解析自己的类型元数据，不读取另一应用的缓存。"""
    first = DependencyContainer()
    second = DependencyContainer()
    for container in (first, second):
        container.register_component(CacheLeaf, CacheLeaf, LifetimeType.SINGLETON, name="current")
        container.register_service(CacheRoot)
        container.build()

    first_root = first.resolve(CacheRoot)
    second_root = second.resolve(CacheRoot)
    assert first_root is not second_root
    assert first_root.leaf is not second_root.leaf
    assert first._constructor_metadata[CacheRoot] is not second._constructor_metadata[CacheRoot]


def test_prepare_reuses_bindings_without_repository_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """首次图校验后，普通和限定依赖都不重复扫描 Repository 注册表。"""
    container = DependencyContainer()
    container.register_component(CacheLeaf, CacheLeaf, LifetimeType.SCOPED, name="current")
    container.register_service(CacheRoot, LifetimeType.SCOPED)
    container.build()

    def unexpected_lookup(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("已绑定依赖不应再次读取 Repository 注册表")

    monkeypatch.setattr(
        container_module.repository_registrations, "registered_repositories", unexpected_lookup
    )

    first = container.create_scope().resolve(CacheRoot)
    second = container.create_scope().resolve(CacheRoot)
    assert first.leaf is not second.leaf
