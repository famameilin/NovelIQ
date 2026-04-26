"""
AnalysisService 服务级状态机测试。

创建时间: 2026-04-23
任务: P0-analysis-service-state-machine-tests
说明: 覆盖恢复、取消、失败持久化、任务认领等服务级路径，避免状态机逻辑只由路由测试间接保护。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.services.analysis_service import AnalysisService
from src.api.services.task_manager import TaskManager
from src.storage.models import Novel
from src.storage.repositories import RunRepository
from src.storage.session import DatabaseSession


class _StaticSessionFactory:
    """为 AnalysisService 测试提供固定 SQLAlchemy Session。

    创建时间: 2026-04-23
    任务: P0-analysis-service-state-machine-tests
    说明: 复用 db_session fixture，避免服务内部重新连到非测试库。
    """

    def __init__(self, session):
        self._session = session

    def get_session(self):
        """返回不自动关闭的 DatabaseSession 包装。"""
        return DatabaseSession(self._session, auto_close=False)


def _insert_novel(db_session, novel_id: str) -> None:
    """插入状态机测试所需小说主表记录。"""
    db_session.add(
        Novel(
            novel_id=novel_id,
            filename=f"{novel_id}.txt",
            file_path=f"data/uploads/{novel_id}.txt",
            file_size=100,
        )
    )
    db_session.commit()


def _make_service(db_session, *, worker_id: str = "worker-state-machine") -> AnalysisService:
    """构造绑定测试库的 AnalysisService。"""
    return AnalysisService(
        novel_service=MagicMock(),
        task_manager=TaskManager(worker_id=worker_id),
        session_factory=_StaticSessionFactory(db_session),
    )


def test_prepare_task_execution_claim_claims_pending_run(db_session) -> None:
    """pending 任务应被当前 worker 原子认领为 running。"""
    _insert_novel(db_session, "svcclaim")
    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(novel_id="svcclaim")
    service = _make_service(db_session, worker_id="worker-a")

    result = service._prepare_task_execution_claim(run_id[:8])
    refreshed = run_repo.get_run(run_id)

    assert result == "claimed"
    assert refreshed is not None
    assert refreshed["status"] == "running"
    assert refreshed["worker_id"] == "worker-a"
    assert refreshed["heartbeat_at"] is not None


def test_prepare_task_execution_claim_cancels_unclaimed_pending_run(db_session) -> None:
    """已请求取消的 pending 任务应在执行前直接收口为 cancelled。"""
    _insert_novel(db_session, "svccncl")
    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(novel_id="svccncl")
    run_repo.update_run_task_fields(run_id, cancel_requested=True)
    service = _make_service(db_session)

    result = service._prepare_task_execution_claim(run_id[:8])
    refreshed = run_repo.get_run(run_id)

    assert result == "cancelled"
    assert refreshed is not None
    assert refreshed["status"] == "cancelled"
    assert refreshed["cancel_requested"] is False
    assert refreshed["completed_at"] is not None


def test_prepare_task_execution_claim_skips_already_running_run(db_session) -> None:
    """running 任务不应被当前 worker 重复认领。"""
    _insert_novel(db_session, "svcskip1")
    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(novel_id="svcskip1")
    run_repo.update_run_task_fields(run_id, status="running", worker_id="other-worker")
    service = _make_service(db_session)

    result = service._prepare_task_execution_claim(run_id[:8])
    refreshed = run_repo.get_run(run_id)

    assert result == "skipped"
    assert refreshed is not None
    assert refreshed["worker_id"] == "other-worker"


def test_write_failure_to_db_persists_failed_terminal_state(db_session) -> None:
    """环境初始化前失败时，兜底写库应把任务持久化为 failed。"""
    _insert_novel(db_session, "svcfail1")
    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(novel_id="svcfail1")
    service = _make_service(db_session)

    service._write_failure_to_db(run_id[:8], "初始化失败")
    refreshed = run_repo.get_run(run_id)

    assert refreshed is not None
    assert refreshed["status"] == "failed"
    assert refreshed["error"] == "初始化失败"
    assert refreshed["completed_at"] is not None


@pytest.mark.asyncio
async def test_recover_pending_tasks_schedules_pending_and_cancels_requested(db_session) -> None:
    """启动恢复应调度普通 pending，并直接取消已带 cancel_requested 的 pending。"""
    _insert_novel(db_session, "svcrecov")
    run_repo = RunRepository(db_session)
    scheduled_run_id = run_repo.create_run(novel_id="svcrecov")
    cancelled_run_id = run_repo.create_run(novel_id="svcrecov")
    run_repo.update_run_task_fields(cancelled_run_id, cancel_requested=True)
    service = _make_service(db_session)
    service.resume_task = AsyncMock(return_value=scheduled_run_id[:8])

    pending_runs = [run_repo.get_run(scheduled_run_id), run_repo.get_run(cancelled_run_id)]
    pending_runs = [run for run in pending_runs if run is not None]

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(RunRepository, "get_pending_tasks", lambda self: pending_runs)
        scheduled_count, cancelled_count = await service.recover_pending_tasks()

    refreshed_cancelled = run_repo.get_run(cancelled_run_id)

    assert scheduled_count == 1
    assert cancelled_count == 1
    service.resume_task.assert_awaited_once_with("svcrecov", scheduled_run_id[:8])
    assert refreshed_cancelled is not None
    assert refreshed_cancelled["status"] == "cancelled"
    assert refreshed_cancelled["cancel_requested"] is False


@pytest.mark.asyncio
async def test_recover_pending_tasks_continues_after_unexpected_resume_failure(db_session) -> None:
    """
    创建时间: 2026-04-26
    创建者: Codex
    任务: fix-diagnosis-review-findings
    说明: startup recovery 必须按任务级隔离异常；
    单个 pending 恢复时报错时，后续 pending 仍应继续恢复。
    """

    _insert_novel(db_session, "svcrcv02")
    run_repo = RunRepository(db_session)
    first_run_id = run_repo.create_run(novel_id="svcrcv02")
    failing_run_id = run_repo.create_run(novel_id="svcrcv02")
    third_run_id = run_repo.create_run(novel_id="svcrcv02")
    service = _make_service(db_session)

    async def _resume_task(_novel_id: str, task_id: str) -> str:
        if task_id == failing_run_id[:8]:
            raise RuntimeError("resume boom")
        return task_id

    service.resume_task = AsyncMock(side_effect=_resume_task)

    pending_runs = [run_repo.get_run(first_run_id), run_repo.get_run(failing_run_id), run_repo.get_run(third_run_id)]
    pending_runs = [run for run in pending_runs if run is not None]

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(RunRepository, "get_pending_tasks", lambda self: pending_runs)
        scheduled_count, cancelled_count = await service.recover_pending_tasks()

    assert scheduled_count == 2
    assert cancelled_count == 0
    assert service.resume_task.await_count == 3
