"""配置类与同步工厂 Bean 的显式注册装饰器。"""

from ._impl import (
    BeanFactory,
    BeanRegistration,
    bean,
    configuration,
    registered_bean_methods,
    registered_beans,
    registered_configurations,
)

__all__ = [
    "BeanFactory",
    "BeanRegistration",
    "bean",
    "configuration",
    "registered_bean_methods",
    "registered_beans",
    "registered_configurations",
]
