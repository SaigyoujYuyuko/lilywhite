"""并发请求、同请求共享和响应流异常后的 Scoped 清理测试。"""

import asyncio
from importlib import import_module
from pathlib import Path

import pytest
from litestar.exceptions import LitestarException
from litestar.testing import AsyncTestClient

from lilywhite import AppProperties, LilyWhiteApplication


def _build_application(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, package: str) -> LilyWhiteApplication:
    """生成一个带两个同请求协作者和流式路由的临时应用。"""
    root = tmp_path / package
    root.mkdir()
    (root / "__init__.py").write_text('"""并发作用域测试包。"""\n', encoding="utf-8")
    (root / "logic.py").write_text(
        "import asyncio\n"
        "from lilywhite import component, service\n"
        "from lilywhite.utils.registry import LifetimeType\n"
        "@component(lifetime=LifetimeType.SCOPED)\n"
        "class RequestState:\n"
        "    active = 0\n"
        "    max_active = 0\n"
        "    instances = []\n"
        "    def __init__(self) -> None:\n"
        "        self.closed = False\n"
        "        type(self).instances.append(self)\n"
        "        type(self).active += 1\n"
        "        type(self).max_active = max(type(self).max_active, type(self).active)\n"
        "    async def close(self) -> None:\n"
        "        self.closed = True\n"
        "        type(self).active -= 1\n"
        "@component(lifetime=LifetimeType.SCOPED)\n"
        "class FirstCollaborator:\n"
        "    def __init__(self, state: RequestState) -> None:\n"
        "        self.state = state\n"
        "@component(lifetime=LifetimeType.SCOPED)\n"
        "class SecondCollaborator:\n"
        "    def __init__(self, state: RequestState) -> None:\n"
        "        self.state = state\n"
        "@service(lifetime=LifetimeType.SCOPED)\n"
        "class ProbeService:\n"
        "    def __init__(\n"
        "        self,\n"
        "        state: RequestState,\n"
        "        first: FirstCollaborator,\n"
        "        second: SecondCollaborator,\n"
        "    ) -> None:\n"
        "        self.state = state\n"
        "        self.first = first\n"
        "        self.second = second\n"
        "    async def snapshot(self) -> dict[str, int | bool]:\n"
        "        await asyncio.sleep(0.02)\n"
        "        return {\n"
        "            'identifier': id(self.state),\n"
        "            'shared': self.first.state is self.state and self.second.state is self.state,\n"
        "        }\n",
        encoding="utf-8",
    )
    (root / "web.py").write_text(
        "from collections.abc import AsyncGenerator\n"
        "from litestar import Controller, get\n"
        "from litestar.di import NamedDependency\n"
        "from litestar.response import Stream\n"
        "from lilywhite import controller\n"
        "from .logic import ProbeService\n"
        "@controller('/scope')\n"
        "class ProbeController(Controller):\n"
        "    @get('/probe')\n"
        "    async def probe(\n"
        "        self, probe_service: NamedDependency[ProbeService]\n"
        "    ) -> dict[str, int | bool]:\n"
        "        return await probe_service.snapshot()\n"
        "    @get('/stream')\n"
        "    async def stream(\n"
        "        self, probe_service: NamedDependency[ProbeService]\n"
        "    ) -> Stream:\n"
        "        async def chunks() -> AsyncGenerator[bytes]:\n"
        "            yield b'first'\n"
        "            raise RuntimeError('stream failed')\n"
        "        return Stream(chunks())\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    return LilyWhiteApplication(AppProperties(), business_package=package)


def test_concurrent_requests_isolate_and_share_scoped_instances(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """并发请求使用不同 State，同请求的两个协作者共享同一 State。"""
    package = "concurrent_scope_app"
    framework = _build_application(tmp_path, monkeypatch, package)

    async def exercise() -> None:
        async with AsyncTestClient(framework.create_app()) as client:
            responses = await asyncio.gather(*(client.get("/scope/probe") for _ in range(12)))
        payloads = [response.json() for response in responses]
        assert all(response.status_code == 200 for response in responses)
        assert all(payload["shared"] for payload in payloads)
        assert len({payload["identifier"] for payload in payloads}) == 12

        state_type = import_module(f"{package}.logic").RequestState
        assert state_type.active == 0
        assert len(state_type.instances) == 12
        assert all(instance.closed for instance in state_type.instances)

    asyncio.run(exercise())


def test_response_stream_exception_closes_request_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """响应已经开始后发生流异常，也必须关闭该请求创建的 Scoped 资源。"""
    package = "streaming_failure_scope_app"
    framework = _build_application(tmp_path, monkeypatch, package)

    async def exercise() -> None:
        async with AsyncTestClient(framework.create_app()) as client:
            with pytest.raises(LitestarException, match="after response started"):
                async with client.stream("GET", "/scope/stream") as response:
                    async for _chunk in response.aiter_bytes():
                        pass

        state_type = import_module(f"{package}.logic").RequestState
        assert state_type.active == 0
        assert len(state_type.instances) == 1
        assert state_type.instances[0].closed

    asyncio.run(exercise())
