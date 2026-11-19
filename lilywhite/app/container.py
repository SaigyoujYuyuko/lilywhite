"""类型驱动的构造器注入、生命周期管理与 Litestar DI 桥接。"""

import re
from collections.abc import Callable, Iterator, Mapping
from inspect import Parameter, signature
from typing import Protocol, cast, get_type_hints

from litestar import Request
from litestar.datastructures import State
from litestar.di import Provide

from ..config import AppProperties
from ..lifecycle import ManagedComponent, RequestScopedResource
from ..logger import LoggerManager
from ..services import registry as service_registrations
from ..storage import registry as repository_registrations
from ..utils import component as component_registrations
from ..utils.registry import LifetimeType
from .discovery import BackendSelection, import_decorated_modules, import_package_modules, normalize_backends

log = LoggerManager.get_logger("DI")


class _Constructor(Protocol):
    """接受关键字依赖并返回实例的动态构造器。"""

    def __call__(self, **kwargs: object) -> object:
        """构造一个对象实例。"""
        ...


class DependencyInjectionException(RuntimeError):
    """依赖注册、解析、生命周期或构造失败。"""


def _type_name(target: type[object]) -> str:
    """返回用于错误信息和日志的完整类型名。"""
    return f"{target.__module__}.{target.__qualname__}"


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
        """绑定应用容器并创建当前作用域的实例表。"""
        self._container = container
        self._instances: dict[type[object], object] = {}
        self._resolving: list[type[object]] = []

    def resolve[T](self, target: type[T]) -> T:
        """按目标生命周期解析当前作用域内的实例。"""
        lifetime = self._container._prepare(target)
        if lifetime is LifetimeType.SINGLETON:
            return cast(T, self._container._resolve_singleton(target))
        if lifetime is LifetimeType.SCOPED and target in self._instances:
            log.trace("scoped cache hit target={}", _type_name(target))
            return cast(T, self._instances[target])
        if target in self._resolving:
            cycle = " -> ".join(_type_name(item) for item in (*self._resolving, target))
            raise DependencyInjectionException(f"检测到循环依赖：{cycle}")

        self._resolving.append(target)
        try:
            instance = self._container._construct(target, self)
        finally:
            self._resolving.pop()
        if lifetime is LifetimeType.SCOPED:
            self._instances[target] = instance
        log.debug("dependency constructed target={} lifetime={}", _type_name(target), lifetime.value)
        return cast(T, instance)

    async def close(self) -> None:
        """按构造逆序关闭当前作用域的资源，并允许重复调用。"""
        instances = list(self._instances.values())
        self._instances.clear()
        for instance in reversed(instances):
            if isinstance(instance, RequestScopedResource):
                await instance.close()


class DependencyContainer:
    """按构造器类型提示和生命周期创建依赖并生成 Litestar 依赖表。"""

    def __init__(
        self,
        backends: BackendSelection,
        *,
        package_names: tuple[str, ...] | None = None,
    ) -> None:
        """保存启用后端、包边界并初始化类型和生命周期注册表。"""
        self._backends = normalize_backends(backends)
        self._package_names = package_names
        self._instances: dict[type[object], object] = {}
        self._lifetimes: dict[type[object], LifetimeType] = {}
        self._implementations: dict[type[object], type[object]] = {}
        self._services: set[type[object]] = set()
        self._resolving: list[type[object]] = []

    def create_scope(self) -> DependencyScope:
        """为后台任务创建显式、由调用方关闭的依赖作用域。"""
        return DependencyScope(self)

    @property
    def request_scope_key(self) -> str:
        """返回当前容器在 ASGI 请求作用域中的键。"""
        return f"_lilywhite_dependency_scope_{id(self)}"

    def register_instance[T](self, target: type[T], instance: T) -> None:
        """把已有资源注册为应用级单例。"""
        log.debug("resource registered type={} lifetime=singleton", _type_name(target))
        self._instances[target] = instance
        self._lifetimes[target] = LifetimeType.SINGLETON
        self._implementations[target] = target

    def register_service(
        self,
        service_type: type[object],
        lifetime: LifetimeType = LifetimeType.SINGLETON,
    ) -> None:
        """注册可暴露给 Controller 的 Service 及其生命周期。"""
        log.debug("service registered service={} lifetime={}", _type_name(service_type), lifetime.value)
        self._services.add(service_type)
        self._lifetimes[service_type] = lifetime
        self._implementations[service_type] = service_type

    def register_component(
        self,
        interface: type[object],
        implementation: type[object],
        lifetime: LifetimeType,
    ) -> None:
        """注册可注入但不直接暴露给Controller的基础设施组件。"""
        log.debug(
            "component registered interface={} implementation={} lifetime={}",
            _type_name(interface),
            _type_name(implementation),
            lifetime.value,
        )
        self._lifetimes[interface] = lifetime
        self._implementations[interface] = implementation

    def managed_components(self) -> Iterator[ManagedComponent]:
        """返回已构造且实现生命周期协议的Singleton，按实现去重。"""
        seen: set[int] = set()
        for instance in self._instances.values():
            if id(instance) not in seen and isinstance(instance, ManagedComponent):
                seen.add(id(instance))
                yield instance

    def build(self) -> None:
        """验证完整依赖图并提前创建全部 Singleton。"""
        log.debug("dependency graph build start services={}", len(self._services))
        for service_type in sorted(self._services, key=_type_name):
            self._validate(service_type, ())
        for service_type in sorted(self._services, key=_type_name):
            if self._lifetimes[service_type] is LifetimeType.SINGLETON:
                self._resolve_singleton(service_type)
        log.debug("dependency graph build complete services={}", len(self._services))

    def resolve[T](self, target: type[T]) -> T:
        """在请求作用域外解析 Singleton，拒绝无请求上下文的 Scoped 和 Transient。"""
        lifetime = self._prepare(target)
        if lifetime is not LifetimeType.SINGLETON:
            raise DependencyInjectionException(
                f"{lifetime.value} 依赖只能在请求作用域内解析：{_type_name(target)}"
            )
        return cast(T, self._resolve_singleton(target))

    def litestar_dependencies(self) -> dict[str, Provide]:
        """按生命周期把 Service 转换为 Litestar 命名依赖。"""
        dependencies: dict[str, Provide] = {}
        for service_type in sorted(self._services, key=_type_name):
            name = dependency_name(service_type)
            lifetime = self._lifetimes[service_type]
            log.trace(
                "litestar provide name={} service={} lifetime={}",
                name,
                _type_name(service_type),
                lifetime.value,
            )
            if lifetime is LifetimeType.SINGLETON:
                dependencies[name] = _provide(self._instances[service_type])
            else:
                factory = self._http_factory(service_type)
                dependencies[name] = Provide(factory, use_cache=False, sync_to_thread=False)
        log.debug("litestar dependencies ready count={}", len(dependencies))
        return dependencies

    def _prepare(self, target: type[object]) -> LifetimeType:
        """解析目标实现和生命周期，未注册类型直接失败。"""
        if target in self._lifetimes:
            return self._lifetimes[target]

        candidates = [
            (backend, registration)
            for backend in self._backends
            for registration in repository_registrations.registered_repositories(
                target,
                backend,
                package_names=self._package_names,
            )
        ]
        if not candidates:
            raise DependencyInjectionException(f"依赖未注册：{_type_name(target)}")
        if len(candidates) > 1:
            raise DependencyInjectionException(f"依赖存在多个实现：{_type_name(target)}")
        backend, registration = candidates[0]
        self._lifetimes[target] = registration.lifetime
        self._implementations[target] = registration.implementation
        log.debug(
            "repository binding interface={} implementation={} backend={} lifetime={}",
            _type_name(target),
            _type_name(registration.implementation),
            backend,
            registration.lifetime.value,
        )
        return registration.lifetime

    def _validate(self, target: type[object], chain: tuple[type[object], ...]) -> None:
        """不创建实例地验证依赖完整性、循环和生命周期约束。"""
        if target in self._instances:
            return
        if target in chain:
            cycle = " -> ".join(_type_name(item) for item in (*chain, target))
            raise DependencyInjectionException(f"检测到循环依赖：{cycle}")

        lifetime = self._prepare(target)
        implementation = self._implementations[target]
        for name, dependency in self._constructor_dependencies(implementation):
            dependency_lifetime = self._prepare(dependency)
            if lifetime is LifetimeType.SINGLETON and dependency_lifetime is not LifetimeType.SINGLETON:
                raise DependencyInjectionException(
                    f"Singleton 不能捕获 {dependency_lifetime.value} 依赖："
                    f"{_type_name(target)}.{name} -> {_type_name(dependency)}"
                )
            self._validate(dependency, (*chain, target))

    def _resolve_singleton(self, target: type[object]) -> object:
        """创建或返回应用级 Singleton。"""
        if target in self._instances:
            log.trace("singleton cache hit target={}", _type_name(target))
            return self._instances[target]
        if self._prepare(target) is not LifetimeType.SINGLETON:
            raise DependencyInjectionException(f"非 Singleton 不能进入应用实例表：{_type_name(target)}")
        if target in self._resolving:
            cycle = " -> ".join(_type_name(item) for item in (*self._resolving, target))
            raise DependencyInjectionException(f"检测到循环依赖：{cycle}")

        self._resolving.append(target)
        try:
            instance = self._construct(target, None)
        finally:
            self._resolving.pop()
        implementation = self._implementations[target]
        self._instances[target] = instance
        self._instances[implementation] = instance
        log.debug("dependency constructed target={} lifetime=singleton", _type_name(target))
        return instance

    def _http_factory(
        self,
        target: type[object],
    ) -> Callable[[Request[object, object, State]], object]:
        """创建只暴露 Request 参数的 Litestar 依赖工厂。"""

        def resolve(request: Request[object, object, State]) -> object:
            """从当前请求作用域解析目标 Service。"""
            return self._resolve_http(target, request)

        return resolve

    def _resolve_http(self, target: type[object], request: Request[object, object, State]) -> object:
        """从当前请求的作用域解析 Service。"""
        return self._request_scope(request).resolve(target)

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

    def _construct(self, target: type[object], scope: DependencyScope | None) -> object:
        """使用单例解析器或请求作用域递归构造目标。"""
        implementation = self._implementations[target]
        arguments: dict[str, object] = {}
        for name, dependency in self._constructor_dependencies(implementation):
            log.trace(
                "constructor inject owner={} parameter={} dependency={}",
                _type_name(implementation),
                name,
                _type_name(dependency),
            )
            if scope is None:
                dependency_lifetime = self._prepare(dependency)
                if dependency_lifetime is not LifetimeType.SINGLETON:
                    raise DependencyInjectionException(
                        f"Singleton 不能捕获 {dependency_lifetime.value} 依赖：{_type_name(dependency)}"
                    )
                arguments[name] = self._resolve_singleton(dependency)
            else:
                arguments[name] = scope.resolve(dependency)

        factory = cast(_Constructor, implementation)
        return factory(**arguments)

    @staticmethod
    def _constructor_dependencies(implementation: type[object]) -> list[tuple[str, type[object]]]:
        """读取构造器参数及其具体类型注解。"""
        if implementation.__init__ is object.__init__:
            return []

        constructor = implementation.__init__
        hints = get_type_hints(constructor)
        dependencies: list[tuple[str, type[object]]] = []
        for name, parameter in signature(constructor).parameters.items():
            if name == "self":
                continue
            if parameter.kind not in (Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY):
                raise DependencyInjectionException(f"构造器参数不受支持：{_type_name(implementation)}.{name}")
            dependency = hints.get(name)
            if not isinstance(dependency, type):
                raise DependencyInjectionException(
                    f"构造器参数缺少具体类型：{_type_name(implementation)}.{name}"
                )
            dependencies.append((name, dependency))
        return dependencies


def create_container(
    *,
    properties: AppProperties | None = None,
    backends: BackendSelection = "memory",
    business_package: str | None = None,
    resources: Mapping[type[object], object] | None = None,
) -> DependencyContainer:
    """自动收集框架与业务装饰器，构造限定包边界的依赖图。"""
    enabled_backends = normalize_backends(backends)
    package_names = ("lilywhite",) if business_package is None else ("lilywhite", business_package)
    log.debug(
        "dependency container scan start backends={} business_package={}",
        enabled_backends,
        business_package,
    )
    import_package_modules("lilywhite.utils")
    import_package_modules("lilywhite.services")
    if business_package is not None:
        import_decorated_modules(business_package, enabled_backends)

    properties = properties or AppProperties()
    container = DependencyContainer(enabled_backends, package_names=package_names)
    for component_registration in component_registrations.registered_components(package_names):
        container.register_component(
            component_registration.interface,
            component_registration.implementation,
            component_registration.lifetime,
        )
    container.register_instance(AppProperties, properties)
    for target, instance in (resources or {}).items():
        container.register_instance(target, instance)
    for service_registration in service_registrations.registered_services(package_names):
        container.register_service(service_registration.service_type, service_registration.lifetime)
    container.build()
    return container
