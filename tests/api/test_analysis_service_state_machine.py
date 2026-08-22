"""
AnalysisService 服务级状态机测试。

创建时间: 2026-04-23
任务: P0-analysis-service-state-machine-tests
说明: 覆盖恢复、取消、失败持久化、任务认领等服务级路径，避免状态机逻辑只由路由测试间接保护。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

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
    assert refreshed["started_at"] is not None


def test_update_run_status_completed_persists_completed_at(db_session) -> None:
    """成功收口写入 completed 终态时，应同时记录 completed_at。"""
    _insert_novel(db_session, "svcdone")
    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(novel_id="svcdone")

    run_repo.update_run_status(run_id, "completed")
    refreshed = run_repo.get_run(run_id)

    assert refreshed is not None
    assert refreshed["status"] == "completed"
    assert refreshed["completed_at"] is not None


def test_update_run_status_failed_persists_completed_at(db_session) -> None:
    """失败收口写入 failed 终态时，应同时记录 completed_at。"""
    _insert_novel(db_session, "svcfail2")
    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(novel_id="svcfail2")

    run_repo.update_run_status(run_id, "failed")
    refreshed = run_repo.get_run(run_id)

    assert refreshed is not None
    assert refreshed["status"] == "failed"
    assert refreshed["completed_at"] is not None


def test_get_run_exposes_started_at_after_claim(db_session) -> None:
    """任务被 worker 认领后，get_run 应能读到 started_at。"""
    _insert_novel(db_session, "svcstart")
    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(novel_id="svcstart")
    service = _make_service(db_session, worker_id="worker-b")

    service._prepare_task_execution_claim(run_id[:8])
    refreshed = run_repo.get_run(run_id)

    assert refreshed is not None
    assert refreshed["status"] == "running"
    assert refreshed["started_at"] is not None


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


@pytest.mark.asyncio
async def test_run_analysis_core_skipped_claim_cleans_memory_task(db_session) -> None:
    """
    2026-08-13 P2：claim 返回 skipped（其他执行方持有 DB 真相）时，
    _run_analysis_core 必须清理本进程的内存执行缓存（停心跳），
    防止残留 TaskInfo 的心跳写回覆盖真实 owner 的 worker_id/heartbeat_at。
    """
    _insert_novel(db_session, "svcskip2")
    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(novel_id="svcskip2")
    run_repo.update_run_task_fields(run_id, status="running", worker_id="other-worker")
    service = _make_service(db_session)
    service.task_manager.create_task(run_id[:8], "svcskip2")
    service.env_initializer.init_analysis_environment = MagicMock()

    with patch.object(
        service.task_manager,
        "cancel_completed_task",
        wraps=service.task_manager.cancel_completed_task,
    ) as mock_cleanup:
        await service._run_analysis_core(
            task_id=run_id[:8],
            novel={"novel_id": "svcskip2"},
            skip_stages_builder=MagicMock(),
            num_topics=25,
        )

    mock_cleanup.assert_called_once_with(run_id[:8])
    service.env_initializer.init_analysis_environment.assert_not_called()
    refreshed = run_repo.get_run(run_id)
    assert refreshed is not None
    assert refreshed["status"] == "running"
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


def test_claim_pending_run_closes_cancelling_window_to_cancelled(db_session) -> None:
    """
    2026-08-13 修复 P1：取消信号落在「worker 读 pending」与「原子 claim」之间时，
    claim 的 UPDATE 不命中且状态已变 cancelling。此前返回 skipped 静默退出，
    任务永久卡在无 owner 的 cancelling；修复后应直接收口为 cancelled 终态。
    """
    _insert_novel(db_session, "svccnc2")
    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(novel_id="svccnc2")
    # 模拟用户 cancel 原子地把 pending -> cancelling（无 worker 归属）
    run_repo.request_task_cancellation(run_id)
    service = _make_service(db_session)

    result = service._claim_pending_run(run_repo, run_id)
    refreshed = run_repo.get_run(run_id)

    assert result == "cancelled"
    assert refreshed is not None
    assert refreshed["status"] == "cancelled"
    assert refreshed["cancel_requested"] is False
    assert refreshed["worker_id"] is None
    assert refreshed["completed_at"] is not None


def test_claim_pending_run_skips_cancelling_with_owner(db_session) -> None:
    """有 worker 归属的 cancelling 由该 worker 收尾，其他 worker 应跳过而非收口。"""
    _insert_novel(db_session, "svccnc3")
    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(novel_id="svccnc3")
    run_repo.request_task_cancellation(run_id)
    run_repo.update_run_task_fields(run_id, worker_id="owner-worker")
    service = _make_service(db_session)

    result = service._claim_pending_run(run_repo, run_id)
    refreshed = run_repo.get_run(run_id)

    assert result == "skipped"
    assert refreshed is not None
    assert refreshed["status"] == "cancelling"
    assert refreshed["worker_id"] == "owner-worker"


@pytest.mark.asyncio
async def test_run_analysis_core_persists_db_terminal_state_when_env_init_fails(db_session) -> None:
    """
    2026-08-13 修复 P1：环境初始化失败（session/run_id 均未建立）时，
    通用异常分支此前只改内存任务状态，DB 停留在 running 无终态；
    修复后必须通过兜底路径把 failed + error 写入 DB。
    """

    _insert_novel(db_session, "svcfail3")
    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(novel_id="svcfail3")
    service = _make_service(db_session)

    # 注意：不预先 claim——_run_analysis_core 内部会自行领取（首次 claim 必成功）；
    # 预 claim 会让内部第二次 claim 失败返回 skipped、提前 return 测不到失败路径
    service.env_initializer.init_analysis_environment = MagicMock(side_effect=RuntimeError("db 连接失败"))

    await service._run_analysis_core(
        task_id=run_id[:8],
        novel={"novel_id": "svcfail3"},
        skip_stages_builder=MagicMock(),
        num_topics=25,
    )

    refreshed = run_repo.get_run(run_id)
    assert refreshed is not None
    assert refreshed["status"] == "failed"
    assert refreshed["error"] == "db 连接失败"
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


def test_is_recent_resume_reset_compares_heartbeat_in_utc(db_session) -> None:
    """
    2026-08-13 P2: 写入端与孤儿回收均以 UTC 落库（DateTime 列无时区，tz 被剥离），
    _is_recent_resume_reset 必须按 UTC 挂钟比较；本地时区（如 UTC+8）下若按
    本地挂钟比较，会把新鲜心跳误判为陈旧，导致真实取消被当作 resume 后陈旧取消。
    """
    from datetime import UTC, datetime, timedelta

    from src.api.services.analysis_service import _RESUME_RESET_WINDOW_SECONDS

    _insert_novel(db_session, "svchb01")
    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(novel_id="svchb01")
    service = _make_service(db_session)
    fresh_utc = datetime.now(UTC) - timedelta(seconds=_RESUME_RESET_WINDOW_SECONDS - 5)

    # 写入端落库剥离 tz（naive UTC），读回补 UTC 后仍判定为新鲜
    db_session.execute(
        text("UPDATE analysis_runs SET worker_id = NULL, heartbeat_at = :hb WHERE run_id = :rid"),
        {"hb": fresh_utc.replace(tzinfo=None), "rid": run_id},
    )
    db_session.commit()

    refreshed = run_repo.get_run(run_id)
    assert refreshed is not None
    assert service._is_recent_resume_reset(refreshed) is True

    # 陈旧心跳（超过窗口）判定为不新鲜
    stale_utc = datetime.now(UTC) - timedelta(seconds=_RESUME_RESET_WINDOW_SECONDS + 3600)
    db_session.execute(
        text("UPDATE analysis_runs SET heartbeat_at = :hb WHERE run_id = :rid"),
        {"hb": stale_utc.replace(tzinfo=None), "rid": run_id},
    )
    db_session.commit()
    refreshed = run_repo.get_run(run_id)
    assert refreshed is not None
    assert service._is_recent_resume_reset(refreshed) is False

    # worker_id 非空时不进入竞态窗口判断
    refreshed["worker_id"] = "worker-other"
    assert service._is_recent_resume_reset(refreshed) is False


@pytest.mark.asyncio
async def test_run_analysis_core_emits_cancelled_event_when_claim_cancelled(db_session, monkeypatch) -> None:
    """
    2026-08-14 P2-10：claim 前取消必须补发 SSE task_cancelled 终态事件，
    否则已连接的客户端永远等不到取消信号
    """
    _insert_novel(db_session, "svcevt1")
    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(novel_id="svcevt1")
    run_repo.update_run_task_fields(run_id, cancel_requested=True)
    service = _make_service(db_session, worker_id="worker-evt1")
    service.task_manager.create_task(run_id[:8], "svcevt1")

    sent: list[tuple[str, str, dict]] = []

    async def fake_send(task_id: str, event_type: str, data: dict) -> None:
        sent.append((task_id, event_type, data))

    monkeypatch.setattr("src.api.services.analysis_service.event_manager.send", fake_send)

    await service._run_analysis_core(
        task_id=run_id[:8],
        novel={"novel_id": "svcevt1"},
        skip_stages_builder=MagicMock(),
        num_topics=25,
    )

    assert sent == [(run_id[:8], "task_cancelled", {"stage": "cancelled", "message": "任务已取消"})]
    refreshed = run_repo.get_run(run_id)
    assert refreshed is not None
    assert refreshed["status"] == "cancelled"


@pytest.mark.asyncio
async def test_run_analysis_core_cancel_after_stages_persists_cancelled(db_session, monkeypatch) -> None:
    """
    2026-08-14 P2-13：所有阶段完成但成功收口前收到取消时，必须落 cancelled 终态
    （此前直接 return，run 卡在 running 直到重启孤儿回收）
    """
    from src.api.services.analysis.error_handler import AnalysisErrorHandler

    _insert_novel(db_session, "svcevt2")
    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(novel_id="svcevt2")
    service = _make_service(db_session, worker_id="worker-evt2")
    service.task_manager.create_task(run_id[:8], "svcevt2")
    service.error_handler = AnalysisErrorHandler(
        novel_service=service.novel_service,
        task_manager=service.task_manager,
    )

    monkeypatch.setattr(service, "_prepare_task_execution_claim", lambda task_id: "claimed")
    monkeypatch.setattr(service, "_is_cancelled", lambda task_id: True)
    monkeypatch.setattr(
        service.env_initializer,
        "init_analysis_environment",
        lambda task_id, novel: ("svcevt2", None, None, db_session, None, run_id),
    )

    async def _noop(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(service, "_call_execute_analysis_stages", _noop)

    await service._run_analysis_core(
        task_id=run_id[:8],
        novel={"novel_id": "svcevt2"},
        skip_stages_builder=MagicMock(),
        num_topics=25,
    )

    refreshed = run_repo.get_run(run_id)
    assert refreshed is not None
    assert refreshed["status"] == "cancelled"
    assert refreshed["completed_at"] is not None
    assert refreshed["cancel_requested"] is False


@pytest.mark.asyncio
async def test_error_handler_skips_terminal_write_when_run_reclaimed(db_session) -> None:
    """
    2026-08-14 P2-13：旧 worker 的延迟取消写回在 run 已被新 worker（resume 后）
    接管时被归属守卫跳过，不得覆写新轮 running 状态
    """
    from datetime import UTC, datetime

    from src.api.services.analysis.error_handler import AnalysisErrorHandler

    _insert_novel(db_session, "svcgrd1")
    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(novel_id="svcgrd1")
    # 模拟 resume 后新 worker 已接管
    run_repo.update_run_task_fields(
        run_id,
        status="running",
        worker_id="worker-new",
        heartbeat_at=datetime.now(UTC),
    )
    handler = AnalysisErrorHandler(
        novel_service=MagicMock(),
        task_manager=TaskManager(worker_id="worker-old"),
    )

    await handler.handle_cancel(
        task_id=run_id[:8],
        novel_id="svcgrd1",
        session=db_session,
        run_id=run_id,
        analysis_logger=None,
        bus=None,
    )

    refreshed = run_repo.get_run(run_id)
    assert refreshed is not None
    assert refreshed["status"] == "running"
    assert refreshed["worker_id"] == "worker-new"
