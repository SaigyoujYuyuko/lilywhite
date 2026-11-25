"""声明式响应后台任务的发现、执行、并发和关闭测试。"""

import asyncio
import sys
from pathlib import Path

import pytest
from litestar.testing import TestClient

from lilywhite import AppProperties, BackgroundManager, LilyWhiteApplication, background_task
from lilywhite.utils.tasks import AsyncTaskManager


def _manager(max_concurrency: int = 0) -> tuple[BackgroundManager, AsyncTaskManager]:
    """创建共享同一个底层任务管理器的测试组件。"""
    properties = AppProperties().override(background={"max_concurrency": max_concurrency})
    tasks = AsyncTaskManager()
    return BackgroundManager(tasks, properties), tasks


def test_background_task_completes_real_http_request_without_manual_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """业务任务应经 AST 发现并由 DI 注入，在响应结束后真实执行。"""
    package = "declarative_background_app"
    root = tmp_path / package
    (root / "web").mkdir(parents=True)
    (root / "logic").mkdir()
    state_path = tmp_path / "background-finished.txt"
    (root / "__init__.py").write_text('"""后台任务扫描示例。"""\n', encoding="utf-8")
    (root / "web/__init__.py").write_text('"""HTTP 层。"""\n', encoding="utf-8")
    (root / "logic/__init__.py").write_text('"""业务层。"""\n', encoding="utf-8")
    (root / "logic/tasks.py").write_text(
        "from pathlib import Path\n"
        "from lilywhite import background_task\n"
        "@background_task\n"
        "def record_completion(path: str) -> None:\n"
        "    Path(path).write_text('finished', encoding='utf-8')\n",
        encoding="utf-8",
    )
    (root / "logic/service.py").write_text(
        "from litestar import Response\n"
        "from lilywhite import BackgroundManager, service\n"
        "from lilywhite.http.result import response\n"
        "from .tasks import record_completion\n"
        "@service\n"
        "class TaskService:\n"
        "    def __init__(self, background: BackgroundManager) -> None:\n"
        "        self.background = background\n"
        "    def result(self, path: str) -> Response[dict[str, str]]:\n"
        "        return response(\n"
        "            {'message': 'accepted'},\n"
        "            status=202,\n"
        "            background=self.background.defer(record_completion, path),\n"
        "        )\n",
        encoding="utf-8",
    )
    (root / "web/routes.py").write_text(
        "from litestar import Controller, Response, get\n"
        "from litestar.di import NamedDependency\n"
        "from lilywhite import controller\n"
        "from ..logic.service import TaskService\n"
        '@controller("/custom")\n'
        "class TaskController(Controller):\n"
        '    @get("/task")\n'
        "    async def task(\n"
        "        self,\n"
        "        task_service: NamedDependency[TaskService],\n"
        "    ) -> Response[dict[str, str]]:\n"
        f"        return task_service.result({str(state_path)!r})\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    application = LilyWhiteApplication(
        AppProperties(),
        business_package=package,
        application_name="Background Task Test",
    ).create_app()

    with TestClient(application) as client:
        result = client.get("/custom/task")

    assert result.status_code == 202
    assert result.json() == {"message": "accepted"}
    assert state_path.read_text(encoding="utf-8") == "finished"
    assert f"{package}.logic.tasks" in sys.modules


def test_background_manager_enforces_configured_concurrency() -> None:
    """多个响应任务应共享配置的全局并发上限，并计入统一快照。"""

    async def exercise() -> None:
        active = 0
        maximum = 0

        @background_task
        async def limited_task() -> None:
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.01)
            active -= 1

        manager, tasks = _manager(max_concurrency=2)
        await manager.initialize()
        await asyncio.gather(*(manager.defer(limited_task)() for _ in range(6)))
        await asyncio.sleep(0)

        snapshot = manager.snapshot()
        assert maximum == 2
        assert snapshot.active_tasks == 0
        assert snapshot.spawned_tasks == 6
        assert snapshot.finished_tasks == 6
        assert snapshot.failed_tasks == 0
        await manager.close()
        await tasks.close()

    asyncio.run(exercise())


def test_background_manager_close_waits_for_running_and_queued_tasks() -> None:
    """关闭应先停止接收任务，再等待执行中和排队中的工作自然完成。"""

    async def exercise() -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        finished = 0

        @background_task
        async def waiting_task() -> None:
            nonlocal finished
            started.set()
            await release.wait()
            finished += 1

        manager, tasks = _manager(max_concurrency=1)
        await manager.initialize()
        running = [asyncio.create_task(manager.defer(waiting_task)()) for _ in range(2)]
        await started.wait()
        await asyncio.sleep(0)
        assert manager.snapshot().active_tasks == 2
        closing = asyncio.create_task(manager.close())
        await asyncio.sleep(0)
        assert not closing.done()

        release.set()
        await asyncio.gather(*running)
        await closing
        assert finished == 2
        with pytest.raises(RuntimeError, match="not accepting"):
            manager.defer(waiting_task)
        await tasks.close()

    asyncio.run(exercise())


def test_background_manager_rejects_undeclared_function_and_tracks_failure() -> None:
    """未声明函数不能绕过注册表，已声明任务异常仍由底层管理器回收。"""

    async def exercise() -> None:
        def undeclared() -> None:
            pass

        @background_task
        async def failing_task() -> None:
            raise RuntimeError("expected background failure")

        manager, tasks = _manager()
        await manager.initialize()
        with pytest.raises(ValueError, match="@background_task"):
            manager.defer(undeclared)
        with pytest.raises(RuntimeError, match="expected background failure"):
            await manager.defer(failing_task)()
        await asyncio.sleep(0)
        assert manager.snapshot().failed_tasks == 1
        await manager.close()
        await tasks.close()

    asyncio.run(exercise())
