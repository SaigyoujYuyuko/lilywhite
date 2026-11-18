"""通过 python -m example 启动问候示例。"""

from lilywhite import run

from .application import ExampleApplication

if __name__ == "__main__":
    run(ExampleApplication)
