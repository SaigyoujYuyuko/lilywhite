"""类型与限定名驱动的构造器注入、生命周期管理与 Litestar DI 桥接。"""

import re
from collections.abc import Callable, Iterator, Mapping
from inspect import Parameter, iscoroutinefunction, signature
from typing import Annotated, Protocol, cast, get_args, get_origin, get_type_hints

import msgspec
from litestar import Request
from litestar.datastructures import State
from litestar.di import Provide

from ..config import AppProperties
from ..decorators import component as component_registrations
from ..decorators import repository as repository_registrations
from ..decorators import service as service_registrations
from ..decorators.conditional import condition_enabled
from ..decorators.configuration import _impl as configuration_registrations
from ..decorators.configuration._impl import BeanFactory
from ..lifecycle import (
    AdaptedResource,
    ManagedComponent,
    RequestScopedResource,
    ResourceCloser,
    close_resource,
)
from ..logger import LoggerManager
from ..qualifier import Qualifier, qualifier_name
from ..utils.registry import LifetimeType
from .discovery import import_decorated_modules, import_package_modules

log = LoggerManager.get_logger("DI")


class _Constructor(Protocol):
    """接受关键字依赖并返回实例的动态构造器。"""

    def __call__(self, **kwargs: object) -> object:
        """构造一个对象实例。"""
        ...


class _DependencyKey(msgspec.Struct, frozen=True):
    """类型只描述能力，限定名进一步区分同类型的不同实例。"""

    target: type[object]
    qualifier: str | None = None


class _DependencyParameter(msgspec.Struct, frozen=True):
    """构造器参数名及其完整依赖身份。"""

    name: str
    key: _DependencyKey


class _BeanRegistration(msgspec.Struct, frozen=True):
    """一个已经绑定配置类实例的同步工厂方法及其资源策略。"""

    factory: BeanFactory
    dependencies: list[_DependencyParameter]
    lifetime: LifetimeType
    closer: ResourceCloser | None


class DependencyInjectionException(RuntimeError):
    """依赖注册、解析、生命周期或构造失败。"""


def _type_name(target: type[object]) -> str:
    """返回用于错误信息和日志的完整类型名。"""
    return f"{target.__module__}.{target.__qualname__}"


def _key_name(key: _DependencyKey) -> str:
    """在日志中同时显示依赖类型和限定名。"""
    suffix = "" if key.qualifier is None else f" [qualifier={key.qualifier}]"
    return f"{_type_name(key.target)}{suffix}"


def _dependency_key(target: type[object], qualifier: str | None = None) -> _DependencyKey:
    """创建经过统一限定名校验的依赖身份。"""
    return _DependencyKey(target, qualifier_name(qualifier))


def dependency_name(target: type[object]) -> str:
    """把包含连续大写字母的类型名转换为 Litestar 命名依赖参数名。"""
    separated = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", target.__name__)
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

    def resolve[T](self, target: type[T], qualifier: str | None = None) -> T:
        """按目标类型和可选限定名解析当前作用域内的实例。"""
        return cast(T, self._resolve(_dependency_key(target, qualifier)))

    def _resolve(self, key: _DependencyKey) -> object:
        """按完整依赖身份处理缓存、循环检查和递归构造。"""
        lifetime = self._container._prepare(key)
        if lifetime is LifetimeType.SINGLETON:
            return self._container._resolve_singleton(key)
        if lifetime is LifetimeType.SCOPED and key in self._instances:
            log.trace("scoped cache hit target={}", _key_name(key))
            return self._instances[key]
        if key in self._resolving:
            cycle = " -> ".join(_key_name(item) for item in (*self._resolving, key))
            raise DependencyInjectionException(f"检测到循环依赖：{cycle}")

        self._resolving.append(key)
        try:
            instance = self._container._construct(key, self)
        finally:
            self._resolving.pop()
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
        self._beans: dict[_DependencyKey, _BeanRegistration] = {}
        self._resolving: list[_DependencyKey] = []
        self._checked_unqualified: set[type[object]] = set()
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
        """注册同步工厂方法及其返回类型、限定名和资源策略。"""
        if not condition_enabled(factory, self._properties):
            return
        if iscoroutinefunction(factory):
            raise DependencyInjectionException(f"Bean 工厂必须是同步方法：{factory.__qualname__}")
        return_type = get_type_hints(factory).get("return")
        if not isinstance(return_type, type):
            raise DependencyInjectionException(f"Bean 工厂缺少具体返回类型：{factory.__qualname__}")
        key = _dependency_key(return_type, name)
        if key in self._lifetimes or key in self._beans:
            raise DependencyInjectionException(f"Bean 重复注册：{_key_name(key)}")
        dependencies = self._bean_dependencies(factory)
        bound_factory = factory.__get__(configuration, type(configuration))
        self._beans[key] = _BeanRegistration(bound_factory, dependencies, lifetime, close)
        self._lifetimes[key] = lifetime
        self._implementations[key] = return_type
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
        """验证完整依赖图并提前创建全部 Singleton。"""
        log.debug("dependency graph build start services={}", len(self._services))
        for key in sorted(self._services, key=_key_name):
            self._validate(key, ())
        for key in sorted(self._services, key=_key_name):
            if self._lifetimes[key] is LifetimeType.SINGLETON:
                self._resolve_singleton(key)
        for key in sorted(self._beans, key=_key_name):
            self._validate(key, ())
        for key in sorted(self._beans, key=_key_name):
            if self._lifetimes[key] is LifetimeType.SINGLETON:
                self._resolve_singleton(key)
        log.debug(
            "dependency graph build complete services={} beans={}", len(self._services), len(self._beans)
        )

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
        if lifetime is LifetimeType.SINGLETON:
            dependencies[name] = _provide(self._instances[key])
        else:
            factory = self._http_factory(key)
            dependencies[name] = Provide(factory, use_cache=False, sync_to_thread=False)

    def _prepare(self, key: _DependencyKey) -> LifetimeType:
        """按限定名选择目标实现；未命名注入仍要求唯一候选。"""
        repositories = [
            registration
            for registration in repository_registrations.registered_repositories(
                key.target,
                package_names=self._package_names,
            )
            if condition_enabled(registration.implementation, self._properties)
            and (key.qualifier is None or registration.qualifier == key.qualifier)
        ]
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
        implementation = self._implementations[key]
        self._instances[key] = instance
        self._instances[_DependencyKey(implementation, key.qualifier)] = instance
        log.debug("dependency constructed target={} lifetime=singleton", _key_name(key))
        return instance

    def _http_factory(
        self,
        key: _DependencyKey,
    ) -> Callable[[Request[object, object, State]], object]:
        """创建只暴露 Request 参数的 Litestar 依赖工厂。"""

        def resolve(request: Request[object, object, State]) -> object:
            """从当前请求作用域解析目标 Service。"""
            return self._resolve_http(key, request)

        return resolve

    def _resolve_http(self, key: _DependencyKey, request: Request[object, object, State]) -> object:
        """从当前请求的作用域解析 Service。"""
        return self._request_scope(request)._resolve(key)

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
        """使用单例解析器或请求作用域递归构造目标。"""
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
        if not isinstance(target, type):
            raise DependencyInjectionException(f"{kind}缺少具体类型：{location}")
        return _DependencyParameter(name, _DependencyKey(target, qualifier))


def create_container(
    *,
    properties: AppProperties | None = None,
    business_package: str | None = None,
    resources: Mapping[type[object], object] | None = None,
) -> DependencyContainer:
    """自动收集装饰器，按普通组件、Bean、后备组件的顺序构造依赖图。"""
    package_names = ("lilywhite",) if business_package is None else ("lilywhite", business_package)
    log.debug("dependency container scan start business_package={}", business_package)
    properties = properties or AppProperties()
    import_package_modules("lilywhite.utils")
    import_package_modules("lilywhite.services")
    if business_package is not None:
        import_decorated_modules(business_package, properties=properties)

    container = DependencyContainer(package_names=package_names)
    container.register_instance(AppProperties, properties)
    registrations = tuple(component_registrations.registered_components(package_names))
    for registration in registrations:
        if not registration.fallback:
            container.register_component(
                registration.interface,
                registration.implementation,
                registration.lifetime,
                name=registration.qualifier,
            )
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
        if not registration.fallback:
            continue
        key = _dependency_key(registration.interface, registration.qualifier)
        if key in container._lifetimes:
            log.debug(
                "component fallback skipped target={} implementation={}",
                _key_name(key),
                _type_name(registration.implementation),
            )
            continue
        container.register_component(
            registration.interface,
            registration.implementation,
            registration.lifetime,
            name=registration.qualifier,
        )
    for target, instance in (resources or {}).items():
        container.register_instance(target, instance)
    for service_registration in service_registrations.registered_services(package_names):
        container.register_service(service_registration.service_type, service_registration.lifetime)
    container.build()
    return container
