"""全局异常处理器发现、签名校验、DI 和真实 HTTP 映射测试。"""

from pathlib import Path

import pytest
from litestar import Request, Response
from litestar.testing import TestClient

from lilywhite import LilyWhiteApplication, exception_handler
from lilywhite.config import AppProperties
from lilywhite.http.result import not_found


class ExpectedError(Exception):
    """签名校验使用的预期异常。"""


class OtherError(Exception):
    """与装饰器声明不一致的异常。"""


def _write_package(tmp_path: Path, package_name: str, files: dict[str, str]) -> None:
    """创建可静态发现和导入的临时业务包。"""
    root = tmp_path / package_name
    for relative_path, content in files.items():
        source = root / relative_path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(content, encoding="utf-8")


def test_function_and_di_class_handlers_map_real_http_exceptions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """独立函数和处理器组应自动发现，并通过 Litestar 返回业务响应。"""
    package = "exception_handler_app"
    _write_package(
        tmp_path,
        package,
        {
            "__init__.py": '"""异常处理示例。"""\n',
            "errors.py": (
                "class MissingGreetingError(Exception):\n"
                "    pass\n"
                "class InvalidGreetingError(Exception):\n"
                "    pass\n"
            ),
            "messages.py": (
                "from lilywhite import service\n"
                "@service\n"
                "class ErrorMessages:\n"
                "    def invalid(self, error: Exception) -> str:\n"
                '        return f"DI: {error}"\n'
            ),
            "handlers.py": (
                "from litestar import Request, Response\n"
                "from lilywhite import exception_handler\n"
                "from lilywhite.http.result import bad_request, not_found\n"
                "from .errors import InvalidGreetingError, MissingGreetingError\n"
                "from .messages import ErrorMessages\n"
                "@exception_handler(MissingGreetingError)\n"
                "def missing(req: Request, problem: MissingGreetingError) -> Response[object]:\n"
                '    return not_found(code="missing", message=str(problem))\n'
                "@exception_handler\n"
                "class BusinessExceptionHandlers:\n"
                "    def __init__(self, messages: ErrorMessages) -> None:\n"
                "        self.messages = messages\n"
                "    def invalid(self, req: Request, problem: InvalidGreetingError) -> Response[object]:\n"
                '        return bad_request(code="invalid", message=self.messages.invalid(problem))\n'
                "    def _helper(self) -> None:\n"
                "        pass\n"
            ),
            "routes.py": (
                "from litestar import Controller, get\n"
                "from lilywhite import controller\n"
                "from .errors import InvalidGreetingError, MissingGreetingError\n"
                '@controller("/errors")\n'
                "class ErrorController(Controller):\n"
                '    @get("/missing")\n'
                "    async def missing(self) -> None:\n"
                '        raise MissingGreetingError("Lily is not here")\n'
                '    @get("/invalid")\n'
                "    async def invalid(self) -> None:\n"
                '        raise InvalidGreetingError("bad greeting")\n'
            ),
        },
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    application = LilyWhiteApplication(
        AppProperties(),
        business_package=package,
        controller_packages=(),
    ).create_app()

    with TestClient(application) as client:
        missing = client.get("/errors/missing")
        invalid = client.get("/errors/invalid")

    assert missing.status_code == 404
    assert missing.json() == {"code": "missing", "message": "Lily is not here"}
    assert invalid.status_code == 400
    assert invalid.json() == {"code": "invalid", "message": "DI: bad greeting"}


def test_function_handler_requires_request_annotation() -> None:
    """第一个参数名可以自定义，但必须注解为 Request。"""
    with pytest.raises(TypeError, match="必须注解为 Request"):

        @exception_handler(ExpectedError)
        def invalid(request: str, error: ExpectedError) -> Response[object]:
            return not_found(message=str(error))


def test_function_handler_error_annotation_must_match_decorator() -> None:
    """函数异常注解必须与装饰器显式声明的类型完全一致。"""
    with pytest.raises(TypeError, match="必须与装饰器异常类型一致"):

        @exception_handler(ExpectedError)
        def invalid(request: Request, error: OtherError) -> Response[object]:
            return not_found(message=str(error))


def test_function_handler_requires_response_return_annotation() -> None:
    """缺少 Response 返回注解时在注册阶段失败。"""
    with pytest.raises(TypeError, match="必须注解返回 Response"):

        @exception_handler(ExpectedError)
        def invalid(request: Request, error: ExpectedError) -> None:
            return None


def test_function_handler_must_be_synchronous() -> None:
    """Litestar 异常处理器不能返回协程对象。"""
    with pytest.raises(TypeError, match="必须是同步函数"):

        @exception_handler(ExpectedError)
        async def invalid(request: Request, error: ExpectedError) -> Response[object]:
            return not_found(message=str(error))


def test_class_handler_requires_exception_annotation() -> None:
    """处理器组从异常参数注解确定映射，不能靠方法名猜测。"""
    with pytest.raises(TypeError, match="必须注解为 Exception 子类"):

        @exception_handler
        class InvalidHandlers:
            def invalid(self, request: Request, error: str) -> Response[object]:
                return not_found(message=error)


def test_duplicate_exception_mapping_fails_during_application_assembly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同一业务包的同一异常不能由多个处理器争抢。"""
    package = "duplicate_exception_handler_app"
    _write_package(
        tmp_path,
        package,
        {
            "__init__.py": '"""重复异常处理示例。"""\n',
            "handlers.py": (
                "from litestar import Request, Response\n"
                "from lilywhite import exception_handler\n"
                "from lilywhite.http.result import not_found\n"
                "class DuplicateError(Exception):\n"
                "    pass\n"
                "@exception_handler(DuplicateError)\n"
                "def first(request: Request, error: DuplicateError) -> Response[object]:\n"
                "    return not_found()\n"
                "@exception_handler(DuplicateError)\n"
                "def second(request: Request, error: DuplicateError) -> Response[object]:\n"
                "    return not_found()\n"
            ),
        },
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(ValueError, match="存在多个处理器"):
        LilyWhiteApplication(AppProperties(), business_package=package, controller_packages=())
