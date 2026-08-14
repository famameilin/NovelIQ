"""
API 分析任务列表、删除、运行态写回测试

创建时间: 2026-04-23
任务: 复杂度与耦合审查 P2 - 测试工程化
说明: 从 test_analysis.py 拆出任务生命周期与运行态持久化场景。
"""

import asyncio
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock, call, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.api.models.events import AnalysisEventBus, StreamEvent
from src.api.routes import analysis as analysis_mod
from src.api.services.analysis.error_handler import AnalysisErrorHandler
from src.api.services.analysis_service import AnalysisService, CancellationStateCheckError
from src.api.services.task_application_service import cleanup_task_runtime_before_delete
from src.api.services.task_manager import TaskManager
from src.storage.db import get_session_factory
from src.storage.repositories import RunRepository
from tests.support.analysis_factories import insert_test_novel as _insert_test_novel


class TestAnalysesList:
    """测试分析列表"""

    def test_list_analyses_not_found(self, api_client: TestClient):
        """测试查询不存在小说的分析版本列表"""
        response = api_client.get("/api/novels/nonexistent/tasks")
        assert response.status_code == 200
        data = response.json()
        assert data["novel_id"] == "nonexistent"
        assert data["tasks"] == []

    def test_list_analyses_after_reanalyze(self, api_client: TestClient):
        """测试重新分析后查看版本列表"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                upload_response = api_client.post(
                    "/api/novels/upload", files={"file": ("list_test.txt", file, "text/plain")}
                )

        novel_id = upload_response.json()["novel_id"]

        api_client.post(f"/api/novels/{novel_id}/reanalyze", json={"label": "version1"})
        api_client.post(f"/api/novels/{novel_id}/reanalyze", json={"label": "version2"})

        response = api_client.get(f"/api/novels/{novel_id}/tasks")
        assert response.status_code == 200
        data = response.json()
        assert data["novel_id"] == novel_id
        assert len(data["tasks"]) >= 2


class TestDeleteAnalysis:
    """测试删除分析"""

    @pytest.mark.asyncio
    async def test_cleanup_task_runtime_before_delete_cancels_active_asyncio_task(self):
        """测试删除前会先取消并等待活跃后台协程结束"""

        async def _never_finish():
            await asyncio.sleep(60)

        task_manager = TaskManager()
        task_manager.create_task("task-running", "novel-1")
        task_manager.update_task("task-running", status=analysis_mod.TaskStatus.RUNNING)

        background_task = asyncio.create_task(_never_finish())
        task_manager.store_asyncio_task("task-running", background_task)

        await cleanup_task_runtime_before_delete("task-running", task_manager)

        assert background_task.done()
        assert background_task.cancelled()

    @pytest.mark.asyncio
    async def test_cleanup_task_runtime_before_delete_does_not_rewrite_terminal_db_status(self):
        """测试删除前清理遇到内存脏状态时，不会把 DB 终态误写回 cancelling"""

        async def _never_finish():
            await asyncio.sleep(60)

        # 使用唯一 run_id 避免测试间数据污染（数据库 run_id 字段长度有限制，用短 UUID 前缀）
        run_id = f"cl-{uuid.uuid4().hex[:8]}"
        _insert_test_novel("novcln01")
        with get_session_factory()() as session:
            run_repo = RunRepository(session)
            run_repo.create_run(novel_id="novcln01", run_id=run_id)
            run_repo.update_run_task_fields(
                run_id,
                status="completed",
                completed_at=datetime.now(),
                message="任务已在 DB 中完成",
            )

        task_manager = TaskManager()
        task_manager.create_task(run_id, "novcln01")
        task_manager.set_db_session_factory(lambda: get_session_factory()())

        # 注意：TaskInfo 不再存储 status，此处通过设置 cancel_event 模拟运行中状态
        # 实际业务状态以 DB 为准，内存仅为执行缓存
        background_task = asyncio.create_task(_never_finish())
        task_manager.store_asyncio_task(run_id, background_task)

        await cleanup_task_runtime_before_delete(run_id, task_manager)

        assert background_task.done()
        assert background_task.cancelled()

        with get_session_factory()() as session:
            refreshed_run = RunRepository(session).get_run(run_id)

        assert refreshed_run is not None
        assert refreshed_run["status"] == "completed"
        assert refreshed_run["cancel_requested"] is False

    def test_delete_analysis_not_found(self, api_client: TestClient):
        """测试删除不存在的分析版本"""
        response = api_client.delete("/api/novels/nonexistent/analyses/nonexistent_analysis")
        assert response.status_code == 404

    def test_delete_analysis_success(self, api_client: TestClient):
        """测试删除分析版本成功"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                upload_response = api_client.post(
                    "/api/novels/upload", files={"file": ("delete_test.txt", file, "text/plain")}
                )

        novel_id = upload_response.json()["novel_id"]

        reanalyze_response = api_client.post(f"/api/novels/{novel_id}/reanalyze", json={"label": "to_delete"})
        task_id = reanalyze_response.json()["task_id"]

        delete_response = api_client.delete(f"/api/novels/{novel_id}/tasks/{task_id}")
        assert delete_response.status_code == 200
        data = delete_response.json()
        assert "删除成功" in data["message"] or "任务删除成功" in data["message"]
        assert data["task_id"] == task_id

    def test_delete_task_cleans_db_rows_and_artifacts_for_full_run_id(self, api_client: TestClient):
        """测试删除 task 会清理 full run_id 日志目录、导出文件与关键从表"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                upload_response = api_client.post(
                    "/api/novels/upload", files={"file": ("delete_artifacts_test.txt", file, "text/plain")}
                )

        assert upload_response.status_code == 200
        novel_id = upload_response.json()["novel_id"]
        run_id = "12345678-1234-1234-1234-123456789abc"
        task_id = run_id[:8]

        with get_session_factory()() as session:
            run_repo = RunRepository(session)
            run_repo.create_run(novel_id=novel_id, run_id=run_id)
            run_repo.update_run_task_fields(run_id, status="completed")
            session.execute(
                text(
                    "INSERT INTO chunks (chunk_id, chapter_id, text, run_id) "
                    "VALUES (:chunk_id, :chapter_id, :text, :run_id)"
                ),
                {"chunk_id": 0, "chapter_id": 1, "text": "待删除分块", "run_id": run_id},
            )
            session.execute(
                text(
                    """
                    INSERT INTO global_context (novel_id, novel_title, run_id)
                    VALUES (:novel_id, :novel_title, :run_id)
                    ON CONFLICT (novel_id) DO UPDATE
                    SET novel_title = EXCLUDED.novel_title, run_id = EXCLUDED.run_id
                    """
                ),
                {"novel_id": novel_id, "novel_title": "待删除小说", "run_id": run_id},
            )
            session.commit()

        log_dir = Path("logs") / run_id
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "analysis.log").write_text("test log", encoding="utf-8")
        output_file = Path("outputs") / f"{task_id}.json"
        output_file.write_text("{}", encoding="utf-8")

        delete_response = api_client.delete(f"/api/novels/{novel_id}/tasks/{task_id}")
        assert delete_response.status_code == 200

        with get_session_factory()() as session:
            remaining_run = session.execute(
                text("SELECT COUNT(*) FROM analysis_runs WHERE run_id = :run_id"),
                {"run_id": run_id},
            ).scalar_one()
            remaining_chunks = session.execute(
                text("SELECT COUNT(*) FROM chunks WHERE run_id = :run_id"),
                {"run_id": run_id},
            ).scalar_one()
            remaining_context = session.execute(
                text("SELECT COUNT(*) FROM global_context WHERE run_id = :run_id"),
                {"run_id": run_id},
            ).scalar_one()

        assert remaining_run == 0
        assert remaining_chunks == 0
        assert remaining_context == 0
        assert not log_dir.exists()
        assert not output_file.exists()


class TestRunRepository:
    """测试 RunRepository 的任务运行态更新"""

    def test_update_run_task_fields_can_clear_nullable_runtime_fields(self, db_session):
        """测试 update_run_task_fields 支持将 nullable 运行态字段清空为 None"""
        _insert_test_novel("novel001", session=db_session)
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(novel_id="novel001")

        run_repo.update_run_task_fields(
            run_id,
            stage="annotate",
            sub_stage="phase4",
            message="旧消息",
            error="旧错误",
            completed_at=datetime.now(),
        )

        run_repo.update_run_task_fields(
            run_id,
            status="pending",
            stage=None,
            sub_stage=None,
            message=None,
            error=None,
            cancel_requested=False,
            completed_at=None,
        )

        run = run_repo.get_run(run_id)
        assert run is not None
        assert run["status"] == "pending"
        assert run["stage"] is None
        assert run["sub_stage"] is None
        assert run["message"] is None
        assert run["error"] is None
        assert run["completed_at"] is None

    def test_claim_pending_run_is_atomic(self, db_session):
        """测试 pending 任务只能被一个 worker 原子领取一次"""
        _insert_test_novel("claim001", session=db_session)
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(novel_id="claim001")

        first_claim = run_repo.claim_pending_run(run_id, worker_id="worker-a")
        second_claim = run_repo.claim_pending_run(run_id, worker_id="worker-b")
        run = run_repo.get_run(run_id)

        assert first_claim is True
        assert second_claim is False
        assert run is not None
        assert run["status"] == "running"
        assert run["worker_id"] == "worker-a"


class _ClaimSessionAdapter:
    """把 db_session fixture 包装为 AnalysisService 需要的会话工厂接口"""

    def __init__(self, session: Session):
        self.connection = session

    def __enter__(self) -> "_ClaimSessionAdapter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _ClaimSessionFactory:
    def __init__(self, session: Session):
        self._session = session

    def get_session(self) -> _ClaimSessionAdapter:
        return _ClaimSessionAdapter(self._session)


class TestExecutionClaimResumeRace:
    """测试 resume 与在途取消收尾竞态：claim 恢复被延迟取消写回覆盖的重置"""

    @staticmethod
    def _make_service(db_session: Session) -> AnalysisService:
        return AnalysisService(
            novel_service=MagicMock(),
            task_manager=TaskManager(worker_id="worker-new"),
            session_factory=_ClaimSessionFactory(db_session),
        )

    def test_claim_reactivates_run_reset_by_recent_resume(self, db_session):
        """resume 重置 pending 后旧 worker 延迟写回 cancelled，claim 应重新激活并领取"""
        _insert_test_novel("claimr1", session=db_session)
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(novel_id="claimr1")
        task_id = run_id[:8]

        # 模拟 resume 重置 pending：worker_id=None + heartbeat_at=now（pending 写回自动刷新心跳）
        # 2026-08-13 P2：heartbeat_at 列无时区，落库值统一为 naive UTC 挂钟
        run_repo.update_run_task_fields(
            run_id,
            status="pending",
            cancel_requested=False,
            worker_id=None,
            heartbeat_at=datetime.now(UTC).replace(tzinfo=None),
            completed_at=None,
        )
        # 模拟旧 worker 的延迟取消写回（不触碰 worker_id/heartbeat_at）
        run_repo.update_run_task_fields(
            run_id,
            status="cancelled",
            cancel_requested=False,
            completed_at=datetime.now(UTC),
        )

        claim_result = self._make_service(db_session)._prepare_task_execution_claim(task_id)

        assert claim_result == "claimed"
        run = run_repo.get_run(run_id)
        assert run is not None
        assert run["status"] == "running"
        assert run["worker_id"] == "worker-new"

    def test_claim_does_not_reactivate_genuine_cancel_of_pending_run(self, db_session):
        """真实取消（无 resume 重置痕迹：heartbeat_at 为 None）不得被 claim 复活"""
        _insert_test_novel("claimr2", session=db_session)
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(novel_id="claimr2")
        task_id = run_id[:8]

        run_repo.cancel_unclaimed_pending_run(run_id, message="任务在启动前已取消")

        claim_result = self._make_service(db_session)._prepare_task_execution_claim(task_id)

        assert claim_result == "skipped"
        run = run_repo.get_run(run_id)
        assert run is not None
        assert run["status"] == "cancelled"

    def test_claim_does_not_reactivate_cancel_outside_resume_window(self, db_session):
        """resume 重置痕迹超出窗口（heartbeat_at 陈旧）时不复活，保持 skipped"""
        _insert_test_novel("claimr3", session=db_session)
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(novel_id="claimr3")
        task_id = run_id[:8]

        # 2026-08-13 P2：heartbeat_at 列无时区，落库值统一为 naive UTC 挂钟
        stale = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        run_repo.update_run_task_fields(
            run_id,
            status="pending",
            cancel_requested=False,
            worker_id=None,
            heartbeat_at=stale,
            completed_at=None,
        )
        run_repo.update_run_task_fields(
            run_id,
            status="cancelled",
            cancel_requested=False,
            completed_at=datetime.now(UTC),
        )

        claim_result = self._make_service(db_session)._prepare_task_execution_claim(task_id)

        assert claim_result == "skipped"


class TestCancellationStateCheck:
    """测试取消状态检查失败时不会静默继续执行"""

    def test_is_cancelled_raises_when_db_check_fails(self):
        """测试 DB 取消状态检查失败时抛出明确异常，而不是返回 False"""

        class BrokenDbSession:
            @property
            def connection(self):
                raise RuntimeError("db unavailable")

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

        class BrokenSessionFactory:
            def get_session(self):
                return BrokenDbSession()

        service = AnalysisService(
            novel_service=MagicMock(),
            task_manager=TaskManager(),
            session_factory=BrokenSessionFactory(),
        )

        with pytest.raises(CancellationStateCheckError, match="取消状态检查失败"):
            service._is_cancelled("deadbeef")


class TestAnalysisErrorHandler:
    """测试取消收口时会清理 DB 中的 cancel_requested 脏状态"""

    @pytest.mark.asyncio
    async def test_handle_failure_rolls_back_dirty_session_before_committing_status(self) -> None:
        """
        创建时间: 2026-04-24
        任务: fix-failure-session-rollback-before-status-commit
        说明: 失败收口必须先 rollback 当前 session，避免半成品业务写入跟随失败状态一起提交。
        """
        session = MagicMock()
        handler = AnalysisErrorHandler(
            novel_service=MagicMock(),
            task_manager=MagicMock(),
        )

        with patch("src.api.services.analysis.error_handler.RunRepository") as mock_run_repo_cls:
            # 2026-08-14 P2-13：归属守卫读取 run.worker_id（无归属放行）
            mock_run_repo_cls.return_value.get_run.return_value = {"worker_id": None}
            await handler.handle_failure(
                task_id="task-1",
                novel_id="novel001",
                elapsed=1.2,
                error=RuntimeError("boom"),
                analysis_logger=None,
                session=session,
                run_id="run-1",
                bus=None,
            )

        assert session.method_calls[:2] == [call.rollback(), call.commit()]
        # 2026-08-13：失败收口改用 update_run_task_fields 一并持久化 error 列
        # （completed_at 用 ANY：断言时刻的 now 与调用时刻的 now 存在微秒差）
        mock_run_repo_cls.return_value.update_run_task_fields.assert_called_once_with(
            "run-1",
            status="failed",
            error="boom",
            completed_at=ANY,
        )

    @pytest.mark.asyncio
    async def test_handle_failure_persists_error_message_in_db(self, db_session) -> None:
        """
        2026-08-13 修复 P1：失败路径必须把异常信息持久化到 error 列，
        DB 中 failed 任务 error 恒为 NULL 会让 /status 接口 error 永远 None。
        """
        _insert_test_novel("novel001", session=db_session)
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(novel_id="novel001")
        handler = AnalysisErrorHandler(
            novel_service=MagicMock(),
            task_manager=MagicMock(),
        )

        await handler.handle_failure(
            task_id=run_id[:8],
            novel_id="novel001",
            elapsed=1.0,
            error=RuntimeError("boom"),
            analysis_logger=None,
            session=db_session,
            run_id=run_id,
            bus=None,
        )

        refreshed = run_repo.get_run(run_id)
        assert refreshed is not None
        assert refreshed["status"] == "failed"
        assert refreshed["error"] == "boom"
        assert refreshed["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_handle_cancel_clears_cancel_requested_in_db(self, db_session):
        _insert_test_novel("novel001", session=db_session)
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(novel_id="novel001")
        run_repo.update_run_task_fields(run_id, status="cancelling", cancel_requested=True)

        task_manager = TaskManager()
        task_manager.create_task(run_id[:8], "novel001")
        handler = AnalysisErrorHandler(
            novel_service=MagicMock(),
            task_manager=task_manager,
        )

        await handler.handle_cancel(
            task_id=run_id[:8],
            novel_id="novel001",
            session=db_session,
            run_id=run_id,
            analysis_logger=None,
            bus=None,
        )

        refreshed_run = run_repo.get_run(run_id)
        assert refreshed_run is not None
        assert refreshed_run["status"] == "cancelled"
        assert refreshed_run["cancel_requested"] is False
        assert refreshed_run["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_handle_cancel_rolls_back_dirty_session_before_committing_status(self) -> None:
        """
        创建时间: 2026-04-24
        任务: fix-cancel-session-rollback-before-status-commit
        说明: 取消收口也必须先 rollback 当前 session，避免未提交业务写入跟随 cancel 状态一起提交。
        """
        session = MagicMock()
        handler = AnalysisErrorHandler(
            novel_service=MagicMock(),
            task_manager=MagicMock(),
        )

        with patch("src.api.services.analysis.error_handler.RunRepository") as mock_run_repo_cls:
            # 2026-08-14 P2-13：归属守卫读取 run.worker_id（无归属放行）
            mock_run_repo_cls.return_value.get_run.return_value = {"worker_id": None}
            await handler.handle_cancel(
                task_id="task-1",
                novel_id="novel001",
                session=session,
                run_id="run-1",
                analysis_logger=None,
                bus=None,
            )

        assert session.method_calls[:2] == [call.rollback(), call.commit()]
        mock_run_repo_cls.return_value.update_run_task_fields.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_success_invalidates_shared_metrics_service_cache(self, db_session):
        """测试成功收口会失效依赖注入单例上的聚合缓存，而不是新建临时实例。"""
        _insert_test_novel("novel001", session=db_session)
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(novel_id="novel001")

        task_manager = TaskManager()
        task_manager.create_task(run_id[:8], "novel001")
        handler = AnalysisErrorHandler(
            novel_service=MagicMock(),
            task_manager=task_manager,
        )

        from src.api.dependencies import get_metrics_service

        metrics_service = get_metrics_service()
        metrics_service._cache[metrics_service._get_cache_key(run_id)] = (("cached",), 9999999999.0)

        await handler.handle_success(
            task_id=run_id[:8],
            novel_id="novel001",
            elapsed=1.2,
            analysis_logger=None,
            session=db_session,
            run_id=run_id,
            bus=None,
        )

        assert metrics_service._get_from_cache(run_id) is None

    @pytest.mark.asyncio
    async def test_handle_success_persists_progress_100_and_completed_at(self, db_session):
        """
        2026-08-13 P2：成功收口必须把 progress 归一为 100.0 并落 completed_at，
        避免完成任务的进度停留在最后阶段区间（如 95.x）而 /status 误报未完成。
        """
        _insert_test_novel("novel001", session=db_session)
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(novel_id="novel001")
        run_repo.update_run_task_fields(run_id, progress=95.0)

        task_manager = TaskManager()
        task_manager.create_task(run_id[:8], "novel001")
        handler = AnalysisErrorHandler(
            novel_service=MagicMock(),
            task_manager=task_manager,
        )

        await handler.handle_success(
            task_id=run_id[:8],
            novel_id="novel001",
            elapsed=1.0,
            analysis_logger=None,
            session=db_session,
            run_id=run_id,
            bus=None,
        )

        refreshed = run_repo.get_run(run_id)
        assert refreshed is not None
        assert refreshed["status"] == "completed"
        assert refreshed["progress"] == 100.0
        assert refreshed["completed_at"] is not None


class TestTaskManagerDbWrite:
    """测试 TaskManager 的 DB 写回使用真实 run_id"""

    def test_update_task_resolves_full_run_id_before_writing_db(self):
        """测试 8 位 task_id 写回时会先解析到完整 run_id，而不是直接精确匹配失败"""
        hex_id = uuid.uuid4().hex
        task_id = hex_id[:8]
        full_run_id = f"{task_id}-{hex_id[8:12]}-{hex_id[12:16]}-{hex_id[16:20]}-{hex_id[20:32]}"
        _insert_test_novel("novel001")
        with get_session_factory()() as session:
            run_repo = RunRepository(session)
            run_repo.create_run(novel_id="novel001", run_id=full_run_id)

        task_manager = TaskManager()
        task_manager.set_db_session_factory(lambda: get_session_factory()())
        task_manager.create_task(task_id, "novel001")

        task_manager.update_task(
            task_id,
            status=analysis_mod.TaskStatus.RUNNING,
            progress=12.5,
            stage="annotate",
            message="历史任务继续运行中",
        )

        with get_session_factory()() as session:
            refreshed_run = RunRepository(session).get_run(full_run_id)
        assert refreshed_run is not None
        assert refreshed_run["status"] == "running"
        assert refreshed_run["progress"] == 12.5
        assert refreshed_run["stage"] == "annotate"
        assert refreshed_run["message"] == "历史任务继续运行中"

    def test_update_task_persists_worker_id_and_heartbeat_for_active_task(self):
        """测试活跃运行态写回会自动带上 worker_id 和 heartbeat_at"""
        run_id = str(uuid.uuid4())
        task_id = run_id[:8]
        _insert_test_novel("novel001")

        with get_session_factory()() as session:
            run_repo = RunRepository(session)
            run_repo.create_run(novel_id="novel001", run_id=run_id)

        task_manager = TaskManager(worker_id="worker-test")
        task_manager.set_db_session_factory(lambda: get_session_factory()())
        task_manager.create_task(task_id, "novel001")

        task_manager.update_task(
            task_id,
            status=analysis_mod.TaskStatus.RUNNING,
            progress=1.0,
            stage="preprocess",
            message="开始执行",
        )

        with get_session_factory()() as session:
            refreshed_run = RunRepository(session).get_run(run_id)

        assert refreshed_run is not None
        assert refreshed_run["worker_id"] == "worker-test"
        assert refreshed_run["heartbeat_at"] is not None

    @pytest.mark.asyncio
    async def test_store_asyncio_task_starts_independent_runtime_heartbeat(self):
        """测试没有进度事件时也会通过独立 heartbeat 持续刷新 heartbeat_at"""
        run_id = str(uuid.uuid4())
        task_id = run_id[:8]
        _insert_test_novel("novel001")

        with get_session_factory()() as session:
            run_repo = RunRepository(session)
            run_repo.create_run(novel_id="novel001", run_id=run_id)

        task_manager = TaskManager(worker_id="worker-heartbeat", heartbeat_interval_seconds=0.02)
        task_manager.set_db_session_factory(lambda: get_session_factory()())
        task_manager.create_task(task_id, "novel001")

        async def _silent_long_stage():
            await asyncio.sleep(0.08)

        runtime_task = asyncio.create_task(_silent_long_stage())
        task_manager.store_asyncio_task(task_id, runtime_task)

        await asyncio.sleep(0.035)
        with get_session_factory()() as session:
            first_run = RunRepository(session).get_run(run_id)

        await asyncio.sleep(0.035)
        with get_session_factory()() as session:
            second_run = RunRepository(session).get_run(run_id)

        assert first_run is not None
        assert second_run is not None
        assert first_run["worker_id"] == "worker-heartbeat"
        assert first_run["heartbeat_at"] is not None
        assert second_run["heartbeat_at"] is not None
        assert second_run["heartbeat_at"] >= first_run["heartbeat_at"]

        await runtime_task
        task_manager.complete_task(task_id, success=True)


class TestAnalysisEventBus:
    """测试 SSE 写回失败时不会静默继续执行"""

    @pytest.mark.asyncio
    async def test_emit_raises_when_task_status_persistence_fails(self):
        """测试任务状态写库失败会直接上抛，而不是只打日志继续运行"""
        task_manager = MagicMock()
        task_manager.update_task.side_effect = RuntimeError("db write failed")
        bus = AnalysisEventBus("task-1", task_manager)

        with patch("src.api.services.event_manager.event_manager.send", new=AsyncMock()):
            with pytest.raises(RuntimeError, match="db write failed"):
                await bus.emit(
                    StreamEvent(
                        action="progress",
                        stage="annotate",
                        current=1,
                        total=10,
                        percent=10.0,
                        message="正在写回进度",
                    )
                )
