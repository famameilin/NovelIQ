"任务仅提供状态，取消与领取使用真实执行对象"

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.sse.events import StreamEvent
from src.storage.repositories import RunRepository
from src.work.task_manager import TaskManager
from src.workflows.analysis.error_handler import AnalysisErrorHandler
from src.workflows.application import TaskApplicationService, cleanup_task_runtime_before_delete
from src.workflows.exceptions import TaskApplicationError
from src.workflows.progress import AnalysisEventBus
from src.workflows.service import AnalysisService
from src.workflows.tasks import TaskService
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.storage_fixtures import storage_for, task_for_run


def test_status_and_list_have_no_runtime_details(api_client, db_session):
    novel, run = create_run_with_chunks(db_session, texts=["任务原文。"])
    task = task_for_run(run, db_session)
    response = api_client.get(f"/api/novels/{novel}/tasks/{task}/status")
    assert response.status_code == 200
    assert set(response.json()) == {"novel_id", "task_id", "status"}
    response = api_client.get(f"/api/novels/{novel}/tasks")
    assert response.status_code == 200
    assert set(response.json()["tasks"][0]) == {"novel_id", "task_id", "status"}


def test_claim_and_cancel_only_change_pending(db_session):
    _, run = create_run_with_chunks(db_session, texts=["领取。"])
    repo = RunRepository(db_session)
    repo.update_run_task_fields(run, status="pending")
    assert repo.claim_pending_run(run)
    assert not repo.cancel_pending_run(run)
    assert not repo.claim_pending_run(run)
    repo.update_run_task_fields(run, status="completed")
    assert not repo.cancel_pending_run(run)
    assert repo.get_run(run)["status"] == "completed"


async def test_pending_cancel_cannot_overwrite_terminal_winner(db_session):
    novel, run = create_run_with_chunks(db_session, texts=["取消。"])
    repo = RunRepository(db_session)
    repo.update_run_task_fields(run, status="pending")
    db_session.commit()
    task = task_for_run(run, db_session)
    service = TaskApplicationService(TaskService(), TaskManager())

    def terminal_wins(_run):
        repo.update_run_task_fields(run, status="completed")
        db_session.commit()
        return False

    with patch("src.storage.access.RunAccess.cancel_pending_run", side_effect=terminal_wins):
        with pytest.raises(TaskApplicationError):
            await service.cancel_task(novel, task)
    assert repo.get_run(run)["status"] == "completed"


async def test_cancel_without_execution_object_reports_missing_owner(db_session):
    novel, run = create_run_with_chunks(db_session, texts=["执行。"])
    RunRepository(db_session).update_run_task_fields(run, status="running")
    db_session.commit()
    service = TaskApplicationService(TaskService(), TaskManager())
    with pytest.raises(TaskApplicationError, match="执行对象"):
        await service.cancel_task(novel, task_for_run(run, db_session))
    assert RunRepository(db_session).get_run(run)["status"] == "running"


async def test_cleanup_waits_for_asyncio_task_without_writing_status():
    manager = TaskManager()
    info = manager.create_task("task", "novel")
    background = asyncio.create_task(asyncio.sleep(60))
    manager.store_asyncio_task("task", background)
    await cleanup_task_runtime_before_delete("task", manager)
    assert background.cancelled()
    assert set(vars(info)) == {"task_id", "llm_outputs", "asyncio_task"}


@pytest.mark.parametrize("state", ["completed", "failed", "cancelled"])
async def test_terminal_handlers_persist_status(db_session, state):
    novel, run = create_run_with_chunks(db_session, texts=["终态。"])
    task = task_for_run(run, db_session)
    handler = AnalysisErrorHandler(TaskService(), TaskManager())
    bus = AsyncMock()
    storage = storage_for(db_session)
    if state == "completed":
        await handler.handle_success(task, novel, 0, None, storage, run, bus=bus)
    elif state == "failed":
        await handler.handle_failure(task, novel, 0, RuntimeError("失败"), None, storage, run, bus=bus)
    else:
        await handler.handle_cancel(task, novel, storage, run, None, bus=bus)
    assert RunRepository(db_session).get_run(run)["status"] == state


async def test_terminal_persistence_failure_is_reported():
    storage = MagicMock()
    storage.runs.update_run_task_fields.side_effect = RuntimeError("写入失败")
    with pytest.raises(RuntimeError, match="写入失败"):
        await AnalysisErrorHandler(MagicMock(), TaskManager()).handle_success("task", "novel", 0, None, storage, "run")


async def test_model_stream_and_progress_share_bus_and_keep_real_identity():
    from src.event_bus import EventBus

    messages = []
    runtime = EventBus()

    async def receive(message):
        messages.append(message)

    runtime.handle("analysis.notification", "notifications", receive)
    bus = AnalysisEventBus("task", run_id="run", bus=runtime)
    await bus.emit(StreamEvent(stage="annotate", action="progress", current=1, total=2))
    await bus.emit(StreamEvent(stage="annotate", sub_stage="event", action="output", content="正文",
        invocation_id="agent", stream_id="stream"))
    assert [message.payload["type"] for message in messages] == ["stage_progress", "llm_output"]
    assert messages[0].payload["data"]["current"] == 1
    data = messages[1].payload["data"]
    assert data["invocation_id"] == "agent" and data["agent_type"] == "event"
    assert data["stage"] == "annotate" and data["run_id"] == "run"


async def test_stage_execution_order_uses_formal_outputs(db_session):
    service = AnalysisService(MagicMock(), TaskManager(), session_factory=lambda: storage_for(db_session))
    from src.event_bus import EventBus

    runtime = EventBus()
    runtime.handle("analysis.notification", "notifications", AsyncMock())
    order = []
    for name in ("preprocess", "annotate", "linguistic", "aggregate", "topic_model", "diagnose"):

        async def record(*args, _name=name, **kwargs):
            order.append(_name)

        setattr(service.stage_executor, f"run_{name}", record)
    await service._execute_analysis_stages(
        AnalysisEventBus("task", bus=runtime),
        storage_for(db_session),
        "run",
        None,
        "novel",
        None,
        None,
        {
            f"skip_{name}": False
            for name in ("preprocess", "annotate", "linguistic", "aggregate", "topic_model", "diagnose")
        },
        2,
    )
    assert order == ["preprocess", "annotate", "linguistic", "aggregate", "topic_model", "diagnose"]
