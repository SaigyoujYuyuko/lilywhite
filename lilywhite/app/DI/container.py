"""类型与限定名驱动的构造器注入、生命周期管理与 Litestar DI 桥接。"""

import re
from collections.abc import Callable, Iterator, Mapping
from inspect import Parameter, isawaitable, iscoroutinefunction, signature
from typing import Annotated, Protocol, cast, get_args, get_origin, get_type_hints

import msgspec
from litestar import Request
from litestar.datastructures import State
from litestar.di import Provide

from ...config import AppProperties
from ...decorators import exception_handler as exception_handler_registrations
from ...decorators import repository as repository_registrations
from ...decorators.conditional import condition_enabled
from ...decorators.configuration import _impl as configuration_registrations
from ...decorators.configuration._impl import BeanFactory
from ...decorators.registry import DependencyKind, DependencyRegistration, registered_dependencies
from ...lifecycle import (
    AdaptedResource,
    ManagedComponent,
    RequestScopedResource,
    ResourceCloser,
    close_resource,
)
from ...logger import LoggerManager
from ...qualifier import Qualifier, qualifier_name
from ...utils.registry import LifetimeType, ManagedRegistrySelection
from .discovery import BusinessDiscovery, discover_business_modules, import_package_modules

log = LoggerManager.get_logger("DI")


class _Constructor(Protocol):
    """接受关键字依赖并返回实例的动态构造器。"""

    def __call__(self, **kwargs: object) -> object:
        """构造一个对象实例。"""
        ...


class _DependencyKey(msgspec.Struct, frozen=True):
    """完整类型或参数化类型描述能力，限定名进一步区分不同实例。"""

    target: object
    qualifier: str | None = None


class _DependencyParameter(msgspec.Struct, frozen=True):
    """构造器参数名及其完整依赖身份。"""

    name: str
    key: _DependencyKey


class _BeanRegistration(msgspec.Struct, frozen=True):
    """一个已经绑定配置类实例的工厂方法及其资源策略。"""

    factory: BeanFactory
    dependencies: list[_DependencyParameter]
    lifetime: LifetimeType
    closer: ResourceCloser | None


class DependencyInjectionException(RuntimeError):
    """依赖注册、解析、生命周期或构造失败。"""


def _type_name(target: object) -> str:
    """返回普通或参数化依赖类型的完整可读名称。"""
    if isinstance(target, type):
        return f"{target.__module__}.{target.__qualname__}"
    origin = get_origin(target)
    if origin is not None:
        arguments = ", ".join(_type_name(argument) for argument in get_args(target))
        return f"{_type_name(origin)}[{arguments}]"
    return str(target)


def _key_name(key: _DependencyKey) -> str:
    """在日志中同时显示依赖类型和限定名。"""
    suffix = "" if key.qualifier is None else f" [qualifier={key.qualifier}]"
    return f"{_type_name(key.target)}{suffix}"


def _dependency_key(target: object, qualifier: str | None = None) -> _DependencyKey:
    """创建经过统一限定名校验的依赖身份。"""
    return _DependencyKey(target, qualifier_name(qualifier))


def dependency_name(target: object) -> str:
    """把普通或参数化类型名转换为 Litestar 命名依赖参数名。"""
    origin = target if isinstance(target, type) else get_origin(target)
    if not isinstance(origin, type):
        raise DependencyInjectionException(f"依赖目标不是具体类型：{target}")
    separated = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", origin.__name__)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", separated).lower()


def _provide(instance: object) -> Provide:
    """把已构造的应用单例转换为 Litestar 依赖提供者。"""
    return Provide(lambda: instance, sync_to_thread=False)


class DependencyScope:
    """在一次请求或后台任务内共享 Scoped 实例并创建 Transient 实例。"""

    def __init__(self, container: DependencyContainer) -> None:
        """绑定应用容器并创建当前作用域的实例和资源表。"""
        self._container = container
        self._instances: dict[_DependencyKey, object] = {}
        self._resources: list[tuple[_DependencyKey, object]] = []
        self._resolving: list[_DependencyKey] = []

    async def resolve[T](self, target: type[T], qualifier: str | None = None) -> T:
        """异步解析当前作用域内的同步或异步 Bean。"""
        return cast(T, await self._resolve(_dependency_key(target, qualifier)))

    async def _resolve(self, key: _DependencyKey) -> object:
        """在请求或后台任务中递归构造包含异步工厂的依赖链。"""
        lifetime = self._container._prepare(key)
        if lifetime is LifetimeType.SINGLETON:
            return await self._container._resolve_singleton_async(key)
        if lifetime is LifetimeType.SCOPED and key in self._instances:
            log.trace("scoped cache hit target={}", _key_name(key))
            return self._instances[key]
        if key in self._resolving:
            cycle = " -> ".join(_key_name(item) for item in (*self._resolving, key))
            raise DependencyInjectionException(f"检测到循环依赖：{cycle}")

        self._resolving.append(key)
        try:
            instance = await self._container._construct_async(key, self)
        finally:
            self._resolving.pop()
        return self._cache_scoped(key, lifetime, instance)

    def _cache_scoped(self, key: _DependencyKey, lifetime: LifetimeType, instance: object) -> object:
        """保存作用域实例，并登记需要释放的资源。"""
        if lifetime is LifetimeType.SCOPED:
            self._instances[key] = instance
        if self._container._resource_closer(key) is not None or isinstance(instance, RequestScopedResource):
            self._resources.append((key, instance))
        log.debug("dependency constructed target={} lifetime={}", _key_name(key), lifetime.value)
        return instance

    async def close(self) -> None:
        """按构造逆序释放 Scoped 和 Transient 资源，收集全部关闭错误。"""
        resources = list(self._resources)
        self._resources.clear()
        self._instances.clear()
        errors: list[Exception] = []
        for key, instance in reversed(resources):
            try:
                await self._container._close_scoped_resource(key, instance)
            except Exception as error:  # noqa: BLE001
                errors.append(error)
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise ExceptionGroup("依赖作用域关闭失败", errors)


class DependencyContainer:
    """按构造器类型提示、限定名和生命周期创建依赖并生成 Litestar 依赖表。"""

    def __init__(
        self,
        *,
        package_names: tuple[str, ...] | None = None,
    ) -> None:
        """保存包边界并初始化依赖键、配置和生命周期注册表。"""
        self._package_names = package_names
        self._properties = AppProperties()
        self._instances: dict[_DependencyKey, object] = {}
        self._lifetimes: dict[_DependencyKey, LifetimeType] = {}
        self._implementations: dict[_DependencyKey, type[object]] = {}
        self._services: set[_DependencyKey] = set()
        self._components: set[_DependencyKey] = set()
        self._beans: dict[_DependencyKey, _BeanRegistration] = {}
        self._resolving: list[_DependencyKey] = []
        self._checked_unqualified: set[object] = set()
        self._constructor_metadata: dict[type[object], list[_DependencyParameter]] = {}

    def create_scope(self) -> DependencyScope:
        """为后台任务创建显式、由调用方关闭的依赖作用域。"""
        return DependencyScope(self)

    @property
    def request_scope_key(self) -> str:
        """返回当前容器在 ASGI 请求作用域中的键。"""
        return f"_lilywhite_dependency_scope_{id(self)}"

    def register_instance[T](self, target: type[T], instance: T, *, name: str | None = None) -> None:
        """把已有资源注册为应用级单例，可选限定名用于多实例场景。"""
        key = _dependency_key(target, name)
        if isinstance(instance, AppProperties):
            self._properties = instance
        log.debug("resource registered target={} lifetime=singleton", _key_name(key))
        self._instances[key] = instance
        self._lifetimes[key] = LifetimeType.SINGLETON
        self._implementations[key] = target

    def register_dependency(self, registration: DependencyRegistration) -> None:
        """按统一元数据装配 Component 或 Service，并计算其直接或装饰器条件。"""
        if registration.kind is DependencyKind.REPOSITORY:
            raise ValueError("Repository 元数据由接口候选解析流程装配")
        if not condition_enabled(
            registration.implementation,
            self._properties,
            direct=registration.conditional,
        ):
            return
        if registration.kind is DependencyKind.SERVICE:
            self.register_service(registration.implementation, registration.lifetime)
            return
        self.register_component(
            registration.interface,
            registration.implementation,
            registration.lifetime,
            name=registration.qualifier,
        )

    def register_service(
        self,
        service_type: type[object],
        lifetime: LifetimeType = LifetimeType.SINGLETON,
    ) -> None:
        """注册可暴露给 Controller 的 Service 及其生命周期。"""
        if not condition_enabled(service_type, self._properties):
            return
        key = _dependency_key(service_type)
        if key in self._beans:
            raise DependencyInjectionException(f"Service 与 Bean 重复注册：{_key_name(key)}")
        log.debug("service registered service={} lifetime={}", _key_name(key), lifetime.value)
        self._services.add(key)
        self._lifetimes[key] = lifetime
        self._implementations[key] = service_type

    def register_component(
        self,
        interface: type[object],
        implementation: type[object],
        lifetime: LifetimeType,
        *,
        name: str | None = None,
    ) -> None:
        """注册可注入但不直接暴露给 Controller 的基础设施组件。"""
        if not condition_enabled(implementation, self._properties):
            return
        key = _dependency_key(interface, name)
        if key in self._lifetimes or key in self._beans:
            raise DependencyInjectionException(f"Component 重复注册：{_key_name(key)}")
        log.debug(
            "component registered target={} implementation={} lifetime={}",
            _key_name(key),
            _type_name(implementation),
            lifetime.value,
        )
        self._components.add(key)
        self._lifetimes[key] = lifetime
        self._implementations[key] = implementation

    def register_bean(
        self,
        configuration: object,
        factory: BeanFactory,
        *,
        name: str | None = None,
        lifetime: LifetimeType = LifetimeType.SINGLETON,
        close: ResourceCloser | None = None,
    ) -> None:
        """注册同步或异步工厂方法及其返回类型、限定名和资源策略。"""
        if not condition_enabled(factory, self._properties):
            return
        return_type = get_type_hints(factory).get("return")
        implementation = return_type if isinstance(return_type, type) else get_origin(return_type)
        if not isinstance(implementation, type):
            raise DependencyInjectionException(f"Bean 工厂缺少具体返回类型：{factory.__qualname__}")
        key = _dependency_key(return_type, name)
        if key in self._lifetimes or key in self._beans:
            raise DependencyInjectionException(f"Bean 重复注册：{_key_name(key)}")
        dependencies = self._bean_dependencies(factory)
        bound_factory = factory.__get__(configuration, type(configuration))
        self._beans[key] = _BeanRegistration(bound_factory, dependencies, lifetime, close)
        self._lifetimes[key] = lifetime
        self._implementations[key] = implementation
        log.debug(
            "bean registered target={} factory={}.{} lifetime={}",
            _key_name(key),
            factory.__module__,
            factory.__qualname__,
            lifetime.value,
        )

    def managed_components(self) -> Iterator[ManagedComponent]:
        """返回已构造且实现生命周期协议的 Singleton，按实现去重。"""
        for _, component in self.managed_component_registrations():
            yield component

    def managed_component_registrations(self) -> Iterator[tuple[str, ManagedComponent]]:
        """为每个托管实例生成包含限定名的唯一生命周期名称。"""
        seen: set[int] = set()
        for key, instance in self._instances.items():
            if id(instance) in seen:
                continue
            bean = self._beans.get(key)
            managed: object = instance
            if bean is not None and bean.closer is not None:
                managed = AdaptedResource(instance, bean.closer)
            if not isinstance(managed, ManagedComponent):
                continue
            seen.add(id(instance))
            name = dependency_name(key.target)
            if key.qualifier is not None:
                name = f"{name}_{key.qualifier}"
            yield name, managed

    def build(self) -> None:
        """验证完整依赖图，并提前创建不依赖异步工厂的 Singleton。"""
        log.debug(
            "dependency graph build start services={} components={}",
            len(self._services),
            len(self._components),
        )
        for key in sorted(self._services, key=_key_name):
            self._validate(key, ())
        for key in sorted(self._beans, key=_key_name):
            self._validate(key, ())
        for key in sorted(self._components, key=_key_name):
            self._validate(key, ())
        for key in sorted(self._services, key=_key_name):
            if self._lifetimes[key] is LifetimeType.SINGLETON and not self._requires_async(key):
                self._resolve_singleton(key)
        for key in sorted(self._beans, key=_key_name):
            if self._lifetimes[key] is LifetimeType.SINGLETON and not self._requires_async(key):
                self._resolve_singleton(key)
        for key in sorted(self._components, key=_key_name):
            if self._lifetimes[key] is LifetimeType.SINGLETON and not self._requires_async(key):
                self._resolve_singleton(key)
        log.debug(
            "dependency graph build complete services={} beans={} components={}",
            len(self._services),
            len(self._beans),
            len(self._components),
        )

    async def build_async(self) -> None:
        """在应用 lifespan 中构造异步 Bean 及其下游 Singleton。"""
        self.build()
        for key in sorted(self._services, key=_key_name):
            if self._lifetimes[key] is LifetimeType.SINGLETON and key not in self._instances:
                await self._resolve_singleton_async(key)
        for key in sorted(self._beans, key=_key_name):
            if self._lifetimes[key] is LifetimeType.SINGLETON and key not in self._instances:
                await self._resolve_singleton_async(key)
        for key in sorted(self._components, key=_key_name):
            if self._lifetimes[key] is LifetimeType.SINGLETON and key not in self._instances:
                await self._resolve_singleton_async(key)

    def resolve[T](self, target: type[T], qualifier: str | None = None) -> T:
        """解析 Singleton；Scoped 和 Transient 仍要求显式请求或后台任务作用域。"""
        key = _dependency_key(target, qualifier)
        lifetime = self._prepare(key)
        if lifetime is not LifetimeType.SINGLETON:
            raise DependencyInjectionException(
                f"{lifetime.value} 依赖只能在请求作用域内解析：{_key_name(key)}"
            )
        return cast(T, self._resolve_singleton(key))

    def litestar_dependencies(self) -> dict[str, Provide]:
        """暴露普通 Service，并以限定名暴露命名 Bean。"""
        dependencies: dict[str, Provide] = {}
        for key in sorted(self._services, key=_key_name):
            self._add_litestar_dependency(dependencies, dependency_name(key.target), key)
        for key in sorted(self._beans, key=_key_name):
            if key.qualifier is not None:
                self._add_litestar_dependency(dependencies, key.qualifier, key)
        log.debug("litestar dependencies ready count={}", len(dependencies))
        return dependencies

    def _add_litestar_dependency(
        self,
        dependencies: dict[str, Provide],
        name: str,
        key: _DependencyKey,
    ) -> None:
        """检查全局参数名冲突，再按生命周期创建 Litestar Provider。"""
        if name in dependencies:
            raise DependencyInjectionException(f"Litestar 依赖名称冲突：{name}")
        lifetime = self._lifetimes[key]
        log.trace("litestar provide name={} target={} lifetime={}", name, _key_name(key), lifetime.value)
        if lifetime is LifetimeType.SINGLETON and key in self._instances:
            dependencies[name] = _provide(self._instances[key])
        elif lifetime is LifetimeType.SINGLETON:
            singleton_factory = self._async_singleton_factory(key)
            dependencies[name] = Provide(singleton_factory)
        else:
            http_factory = self._http_factory(key)
            dependencies[name] = Provide(http_factory, use_cache=False)

    def _prepare(self, key: _DependencyKey) -> LifetimeType:
        """复用已校验绑定；仅首次解析时检查候选和 Repository 注册表。"""
        if key.qualifier is not None or key.target in self._checked_unqualified:
            if key in self._instances:
                return LifetimeType.SINGLETON
            if key in self._lifetimes:
                return self._lifetimes[key]

        repositories = (
            [
                registration
                for registration in repository_registrations.registered_repositories(
                    key.target,
                    package_names=self._package_names,
                )
                if condition_enabled(registration.implementation, self._properties)
                and (key.qualifier is None or registration.qualifier == key.qualifier)
            ]
            if isinstance(key.target, type)
            else []
        )
        if key.qualifier is None and key.target not in self._checked_unqualified:
            candidates = {
                (candidate.qualifier, self._implementations[candidate])
                for candidate in self._lifetimes
                if candidate.target is key.target
            }
            candidates.update(
                (registration.qualifier, registration.implementation) for registration in repositories
            )
            if len(candidates) > 1:
                raise DependencyInjectionException(
                    f"依赖存在多个实现，请使用 Qualifier 选择：{_key_name(key)}"
                )
            only_named_candidate = len(candidates) == 1 and next(iter(candidates))[0] is not None
            if only_named_candidate and key not in self._lifetimes:
                raise DependencyInjectionException(f"命名依赖必须使用 Qualifier：{_key_name(key)}")
            self._checked_unqualified.add(key.target)

        if key in self._instances:
            return LifetimeType.SINGLETON
        if key in self._lifetimes:
            return self._lifetimes[key]
        if not repositories:
            raise DependencyInjectionException(f"依赖未注册：{_key_name(key)}")
        if len(repositories) > 1:
            raise DependencyInjectionException(f"限定依赖存在多个实现：{_key_name(key)}")
        registration = repositories[0]
        self._lifetimes[key] = registration.lifetime
        self._implementations[key] = registration.implementation
        log.debug(
            "repository binding target={} implementation={} lifetime={}",
            _key_name(key),
            _type_name(registration.implementation),
            registration.lifetime.value,
        )
        return registration.lifetime

    def _validate(self, key: _DependencyKey, chain: tuple[_DependencyKey, ...]) -> None:
        """不创建实例地验证依赖完整性、循环和生命周期约束。"""
        if key in self._instances:
            return
        if key in chain:
            cycle = " -> ".join(_key_name(item) for item in (*chain, key))
            raise DependencyInjectionException(f"检测到循环依赖：{cycle}")

        lifetime = self._prepare(key)
        for parameter in self._dependencies(key):
            dependency_lifetime = self._prepare(parameter.key)
            if lifetime is LifetimeType.SINGLETON and dependency_lifetime is not LifetimeType.SINGLETON:
                raise DependencyInjectionException(
                    f"Singleton 不能捕获 {dependency_lifetime.value} 依赖："
                    f"{_key_name(key)}.{parameter.name} -> {_key_name(parameter.key)}"
                )
            self._validate(parameter.key, (*chain, key))

    def _resolve_singleton(self, key: _DependencyKey) -> object:
        """创建或返回应用级 Singleton。"""
        if key in self._instances:
            log.trace("singleton cache hit target={}", _key_name(key))
            return self._instances[key]
        if self._prepare(key) is not LifetimeType.SINGLETON:
            raise DependencyInjectionException(f"非 Singleton 不能进入应用实例表：{_key_name(key)}")
        if key in self._resolving:
            cycle = " -> ".join(_key_name(item) for item in (*self._resolving, key))
            raise DependencyInjectionException(f"检测到循环依赖：{cycle}")

        self._resolving.append(key)
        try:
            instance = self._construct(key, None)
        finally:
            self._resolving.pop()
        return self._cache_singleton(key, instance)

    async def _resolve_singleton_async(self, key: _DependencyKey) -> object:
        """在 lifespan 或异步请求工厂中解析 Singleton。"""
        if key in self._instances:
            log.trace("singleton cache hit target={}", _key_name(key))
            return self._instances[key]
        if self._prepare(key) is not LifetimeType.SINGLETON:
            raise DependencyInjectionException(f"非 Singleton 不能进入应用实例表：{_key_name(key)}")
        if key in self._resolving:
            cycle = " -> ".join(_key_name(item) for item in (*self._resolving, key))
            raise DependencyInjectionException(f"检测到循环依赖：{cycle}")

        self._resolving.append(key)
        try:
            instance = await self._construct_async(key, None)
        finally:
            self._resolving.pop()
        return self._cache_singleton(key, instance)

    def _cache_singleton(self, key: _DependencyKey, instance: object) -> object:
        """按公开类型和实现类型缓存同一个 Singleton。"""
        implementation = self._implementations[key]
        self._instances[key] = instance
        self._instances[_DependencyKey(implementation, key.qualifier)] = instance
        log.debug("dependency constructed target={} lifetime=singleton", _key_name(key))
        return instance

    def _async_singleton_factory(self, key: _DependencyKey) -> Callable[[], object]:
        """为尚未在 lifespan 前构造的 Singleton 提供异步 Litestar 工厂。"""

        async def resolve() -> object:
            return await self._resolve_singleton_async(key)

        return resolve

    def _http_factory(
        self,
        key: _DependencyKey,
    ) -> Callable[[Request[object, object, State]], object]:
        """创建统一的异步 Litestar 请求作用域工厂。"""

        async def resolve(request: Request[object, object, State]) -> object:
            """从当前请求作用域解析目标 Service 或命名 Bean。"""
            return await self._request_scope(request)._resolve(key)

        return resolve

    def _request_scope(self, request: Request[object, object, State]) -> DependencyScope:
        """取得或创建当前请求共享的依赖作用域。"""
        key = self.request_scope_key
        scope_values = cast(dict[str, object], request.scope)
        scope = scope_values.get(key)
        if isinstance(scope, DependencyScope):
            return scope
        scope = DependencyScope(self)
        scope_values[key] = scope
        log.trace("request dependency scope created")
        return scope

    def _resource_closer(self, key: _DependencyKey) -> ResourceCloser | None:
        """返回 Bean 显式声明的关闭适配器，其他依赖使用自身 close。"""
        bean = self._beans.get(key)
        return None if bean is None else bean.closer

    async def _close_scoped_resource(self, key: _DependencyKey, instance: object) -> None:
        """统一释放当前作用域创建的 Bean、Service、Repository 或 Component。"""
        await close_resource(instance, self._resource_closer(key))

    def _construct(self, key: _DependencyKey, scope: DependencyScope | None) -> object:
        """同步构造 Singleton；异步依赖链必须先完成应用启动。"""
        if self._requires_async(key):
            raise DependencyInjectionException(f"依赖需要异步构造，请等待应用启动完成：{_key_name(key)}")
        implementation = self._implementations[key]
        arguments: dict[str, object] = {}
        for parameter in self._dependencies(key):
            log.trace(
                "constructor inject owner={} parameter={} dependency={}",
                _type_name(implementation),
                parameter.name,
                _key_name(parameter.key),
            )
            if scope is None:
                dependency_lifetime = self._prepare(parameter.key)
                if dependency_lifetime is not LifetimeType.SINGLETON:
                    raise DependencyInjectionException(
                        f"Singleton 不能捕获 {dependency_lifetime.value} 依赖：{_key_name(parameter.key)}"
                    )
                arguments[parameter.name] = self._resolve_singleton(parameter.key)
            else:
                arguments[parameter.name] = scope._resolve(parameter.key)

        bean = self._beans.get(key)
        if bean is not None:
            return bean.factory(**arguments)
        factory = cast(_Constructor, implementation)
        return factory(**arguments)

    async def _construct_async(self, key: _DependencyKey, scope: DependencyScope | None) -> object:
        """递归等待异步 Bean，再构造依赖它的同步或异步对象。"""
        implementation = self._implementations[key]
        arguments: dict[str, object] = {}
        for parameter in self._dependencies(key):
            log.trace(
                "constructor inject owner={} parameter={} dependency={}",
                _type_name(implementation),
                parameter.name,
                _key_name(parameter.key),
            )
            if scope is None:
                dependency_lifetime = self._prepare(parameter.key)
                if dependency_lifetime is not LifetimeType.SINGLETON:
                    raise DependencyInjectionException(
                        f"Singleton 不能捕获 {dependency_lifetime.value} 依赖：{_key_name(parameter.key)}"
                    )
                arguments[parameter.name] = await self._resolve_singleton_async(parameter.key)
            else:
                arguments[parameter.name] = await scope._resolve(parameter.key)

        bean = self._beans.get(key)
        if bean is not None:
            result = bean.factory(**arguments)
            return await result if isawaitable(result) else result
        factory = cast(_Constructor, implementation)
        return factory(**arguments)

    def _requires_async(self, key: _DependencyKey, chain: tuple[_DependencyKey, ...] = ()) -> bool:
        """判断当前 Bean 或其任意构造器依赖是否包含异步工厂。"""
        if key in chain or key in self._instances:
            return False
        bean = self._beans.get(key)
        if bean is not None and iscoroutinefunction(bean.factory):
            return True
        next_chain = (*chain, key)
        return any(self._requires_async(parameter.key, next_chain) for parameter in self._dependencies(key))

    def _dependencies(self, key: _DependencyKey) -> list[_DependencyParameter]:
        """Bean 在注册时缓存，构造器在当前容器的首次图校验时缓存。"""
        bean = self._beans.get(key)
        if bean is not None:
            return bean.dependencies
        implementation = self._implementations[key]
        dependencies = self._constructor_metadata.get(implementation)
        if dependencies is None:
            dependencies = self._constructor_dependencies(implementation)
            self._constructor_metadata[implementation] = dependencies
        return dependencies

    @staticmethod
    def _bean_dependencies(factory: BeanFactory) -> list[_DependencyParameter]:
        """读取工厂方法参数，self 由所属配置类实例提供。"""
        hints = get_type_hints(factory, include_extras=True)
        dependencies: list[_DependencyParameter] = []
        for name, parameter in signature(factory).parameters.items():
            if name == "self":
                continue
            if parameter.kind not in (Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY):
                raise DependencyInjectionException(f"Bean 工厂参数不受支持：{factory.__qualname__}.{name}")
            dependencies.append(
                DependencyContainer._dependency_parameter(
                    hints.get(name), "Bean 工厂参数", f"{factory.__qualname__}.{name}", name
                )
            )
        return dependencies

    @staticmethod
    def _constructor_dependencies(implementation: type[object]) -> list[_DependencyParameter]:
        """读取构造器参数及其具体类型注解和可选限定名。"""
        if implementation.__init__ is object.__init__:
            return []

        constructor = implementation.__init__
        hints = get_type_hints(constructor, include_extras=True)
        dependencies: list[_DependencyParameter] = []
        for name, parameter in signature(constructor).parameters.items():
            if name == "self":
                continue
            if parameter.kind not in (Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY):
                raise DependencyInjectionException(f"构造器参数不受支持：{_type_name(implementation)}.{name}")
            dependencies.append(
                DependencyContainer._dependency_parameter(
                    hints.get(name), "构造器参数", f"{_type_name(implementation)}.{name}", name
                )
            )
        return dependencies

    @staticmethod
    def _dependency_parameter(
        hint: object,
        kind: str,
        location: str,
        name: str,
    ) -> _DependencyParameter:
        """从 Annotated 元数据提取 Qualifier，其余元数据原样忽略。"""
        target = hint
        qualifier: str | None = None
        if get_origin(hint) is Annotated:
            arguments = get_args(hint)
            target = arguments[0]
            qualifiers = [item.name for item in arguments[1:] if isinstance(item, Qualifier)]
            if len(qualifiers) > 1:
                raise DependencyInjectionException(f"依赖参数只能声明一个 Qualifier：{location}")
            if qualifiers:
                qualifier = qualifiers[0]
        if not isinstance(target, type) and not isinstance(get_origin(target), type):
            raise DependencyInjectionException(f"{kind}缺少具体类型：{location}")
        return _DependencyParameter(name, _DependencyKey(target, qualifier))


def create_container(
    *,
    properties: AppProperties | None = None,
    business_package: str | None = None,
    resources: Mapping[type[object], object] | None = None,
    managed_registries: ManagedRegistrySelection = (),
    optional_imports: tuple[str, ...] = (),
    discovery: BusinessDiscovery | None = None,
) -> DependencyContainer:
    """自动收集框架与托管注册表装饰器，再构造依赖图。"""
    package_names = ("lilywhite",) if business_package is None else ("lilywhite", business_package)
    log.debug("dependency container scan start business_package={}", business_package)
    properties = properties or AppProperties()
    import_package_modules("lilywhite.utils")
    import_package_modules("lilywhite.observability")
    if business_package is not None:
        if discovery is None:
            discovery = discover_business_modules(
                business_package,
                properties=properties,
                managed_registries=managed_registries,
            )
        elif discovery.package_name != business_package:
            raise ValueError("业务发现结果与容器包不一致")
        discovery.import_modules(optional_imports)

    container = DependencyContainer(package_names=package_names)
    container.register_instance(AppProperties, properties)
    registrations = tuple(registered_dependencies(package_names))
    for registration in registrations:
        if registration.kind is not DependencyKind.REPOSITORY and not registration.fallback:
            container.register_dependency(registration)
    for configuration_type in configuration_registrations.registered_configurations(package_names):
        if not condition_enabled(configuration_type, properties):
            continue
        try:
            configuration = configuration_type()
        except TypeError as error:
            raise DependencyInjectionException(
                f"配置类构造器必须无参数：{_type_name(configuration_type)}"
            ) from error
        for bean_registration in configuration_registrations.registered_beans(configuration_type):
            container.register_bean(
                configuration,
                bean_registration.factory,
                name=bean_registration.qualifier,
                lifetime=bean_registration.lifetime,
                close=bean_registration.closer,
            )
    for registration in registrations:
        if registration.kind is not DependencyKind.COMPONENT or not registration.fallback:
            continue
        key = _dependency_key(registration.interface, registration.qualifier)
        if key in container._lifetimes:
            log.debug(
                "component fallback skipped target={} implementation={}",
                _key_name(key),
                _type_name(registration.implementation),
            )
            continue
        container.register_dependency(registration)
    for target, instance in (resources or {}).items():
        container.register_instance(target, instance)
    for handler_type in exception_handler_registrations.registered_exception_handler_types(package_names):
        container.register_component(handler_type, handler_type, LifetimeType.SINGLETON)
    container.build()
    return container
