"""
API 分析端点测试

修改时间: 2026-04-05
修改者: AI Assistant
任务: fix-test-data-pollution
修改内容: 使用 api_client fixture 确保测试使用测试数据库

修改时间: 2026-04-19
修改者: Codex (GPT-5)
任务: fix-task-system-review-findings
修改内容: 补充 DB-first 任务系统回归测试，覆盖创建失败、进程外取消、resume 清脏字段、message 持久化
"""

import asyncio
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.routes import analysis as analysis_mod
from src.api.exceptions import NovelNotFoundError
from src.api.models.events import AnalysisEventBus, StreamEvent
from src.api.services.analysis_service import AnalysisService, CancellationStateCheckError
from src.api.services.analysis.error_handler import AnalysisErrorHandler
from src.api.services.novel_service import NovelService
from src.api.services.task_manager import TaskManager
from src.storage.db import get_session_factory
from src.storage.id_mapping import TaskIDNotFoundError
from src.storage.repositories import RunRepository


class TestAnalysis:
    """测试分析端点"""

    def test_create_task_not_found(self, api_client: TestClient):
        """测试创建任务时小说不存在"""
        response = api_client.post("/api/novels/nonexistent/tasks")
        assert response.status_code == 404

    def test_resume_task_not_found(self, api_client: TestClient):
        """测试继续任务时小说不存在"""
        response = api_client.post("/api/novels/nonexistent/tasks/fake1234/resume")
        assert response.status_code == 404

    def test_get_status_requires_task_id(self, api_client: TestClient):
        """测试兼容状态接口必须显式提供 task_id"""
        response = api_client.get("/api/novels/nonexistent/status")
        assert response.status_code == 400
        data = response.json()
        assert "task_id" in data["detail"]

    def test_get_task_status_not_found(self, api_client: TestClient):
        """测试单任务状态接口在任务不存在时返回 404"""
        response = api_client.get("/api/novels/nonexistent/tasks/fake1234/status")
        assert response.status_code == 404

    def test_get_task_status_success(self, api_client: TestClient):
        """测试单任务状态接口可以返回指定任务状态"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                upload_response = api_client.post(
                    "/api/novels/upload", files={"file": ("status_task_test.txt", file, "text/plain")}
                )

        assert upload_response.status_code == 200
        novel_id = upload_response.json()["novel_id"]

        create_response = api_client.post(f"/api/novels/{novel_id}/tasks")
        assert create_response.status_code == 200
        task_id = create_response.json()["task_id"]

        status_response = api_client.get(f"/api/novels/{novel_id}/tasks/{task_id}/status")
        assert status_response.status_code == 200
        data = status_response.json()
        assert data["novel_id"] == novel_id
        assert data["task_id"] == task_id

    def test_list_tasks_includes_created_at(self, api_client: TestClient):
        """测试任务列表会返回 created_at，供前端显示真实创建时间"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                upload_response = api_client.post(
                    "/api/novels/upload", files={"file": ("task_list_created_at_test.txt", file, "text/plain")}
                )

        assert upload_response.status_code == 200
        novel_id = upload_response.json()["novel_id"]

        create_response = api_client.post(f"/api/novels/{novel_id}/tasks")
        assert create_response.status_code == 200
        task_id = create_response.json()["task_id"]

        list_response = api_client.get(f"/api/novels/{novel_id}/tasks")
        assert list_response.status_code == 200
        tasks = list_response.json()["tasks"]
        task = next(item for item in tasks if item["task_id"] == task_id)
        assert task["created_at"] is not None

    def test_get_task_status_returns_404_when_db_record_missing(self, api_client: TestClient):
        """测试 DB-only 查询模式下，任务不存在时返回 404"""

        class MissingTaskNovelService:
            def get_task(self, task_id: str):
                raise NovelNotFoundError(message=f"db task missing: {task_id}")

        api_client.app.dependency_overrides[analysis_mod.get_novel_service] = lambda: MissingTaskNovelService()
        try:
            response = api_client.get("/api/novels/novel-1/tasks/memory123/status")
        finally:
            api_client.app.dependency_overrides.pop(analysis_mod.get_novel_service, None)

        assert response.status_code == 404

    def test_get_task_status_returns_500_when_db_query_fails(self, api_client: TestClient):
        """测试 DB 查询异常不会被错误降级成 404"""

        class BrokenNovelService:
            def get_task(self, task_id: str):
                raise RuntimeError(f"db unavailable for {task_id}")

        api_client.app.dependency_overrides[analysis_mod.get_novel_service] = lambda: BrokenNovelService()
        try:
            client = TestClient(api_client.app, raise_server_exceptions=False)
            response = client.get("/api/novels/novel-1/tasks/broken123/status")
        finally:
            api_client.app.dependency_overrides.pop(analysis_mod.get_novel_service, None)

        assert response.status_code == 500

    def test_list_tasks_returns_500_when_db_query_fails(self, api_client: TestClient):
        """测试任务列表查询失败时返回 500，而不是伪装成空列表"""

        class BrokenNovelService:
            def get_tasks_by_novel(self, novel_id: str):
                raise RuntimeError(f"db unavailable for {novel_id}")

        api_client.app.dependency_overrides[analysis_mod.get_novel_service] = lambda: BrokenNovelService()
        try:
            client = TestClient(api_client.app, raise_server_exceptions=False)
            response = client.get("/api/novels/novel-1/tasks")
        finally:
            api_client.app.dependency_overrides.pop(analysis_mod.get_novel_service, None)

        assert response.status_code == 500

    def test_resume_pending_task_success(self, api_client: TestClient):
        """测试继续 pending 任务走专用 resume 路径"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                upload_response = api_client.post(
                    "/api/novels/upload", files={"file": ("resume_task_test.txt", file, "text/plain")}
                )

        assert upload_response.status_code == 200
        novel_id = upload_response.json()["novel_id"]

        # 直接创建 pending 任务，不触发自动分析，确保 resume 语义稳定可测。
        from src.api.dependencies import get_novel_service

        service = get_novel_service()
        task_id = service.create_task(novel_id)

        resume_response = api_client.post(f"/api/novels/{novel_id}/tasks/{task_id}/resume")
        assert resume_response.status_code == 200
        data = resume_response.json()
        assert data["novel_id"] == novel_id
        assert data["task_id"] == task_id

    def test_create_task_raises_when_db_insert_fails(self, api_client: TestClient):
        """测试创建任务时 DB 写入失败会直接抛错，不再静默返回 task_id"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                upload_response = api_client.post(
                    "/api/novels/upload", files={"file": ("create_task_failure_test.txt", file, "text/plain")}
                )

        assert upload_response.status_code == 200
        novel_id = upload_response.json()["novel_id"]
        service = NovelService(upload_dir=Path("data/uploads"))

        with patch("src.api.services.novel_service.RunRepository.create_run", side_effect=RuntimeError("db unavailable")):
            with pytest.raises(RuntimeError, match="db unavailable"):
                service.create_task(novel_id)

    def test_cancel_pending_task_not_in_memory_stays_cancelling_in_db(self, api_client: TestClient):
        """测试 DB-only pending 任务也只会写入取消请求，避免提前写终态后又被真实 worker 覆盖"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                upload_response = api_client.post(
                    "/api/novels/upload", files={"file": ("cancel_out_of_process_test.txt", file, "text/plain")}
                )

        assert upload_response.status_code == 200
        novel_id = upload_response.json()["novel_id"]

        from src.api.dependencies import get_novel_service

        service = get_novel_service()
        task_id = service.create_task(novel_id)

        response = api_client.post(f"/api/novels/{novel_id}/tasks/{task_id}/cancel")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "cancelling"

        with get_session_factory()() as session:
            run = RunRepository(session).get_run(task_id)

        assert run is not None
        assert run["status"] == "cancelling"
        assert run["cancel_requested"] is True
        assert run["completed_at"] is None

    def test_cancel_running_task_not_in_memory_stays_cancelling_in_db(self, api_client: TestClient):
        """测试进程外取消真实 running 任务时仍保留 cancelling，等待执行方收尾"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                upload_response = api_client.post(
                    "/api/novels/upload", files={"file": ("cancel_running_out_of_process_test.txt", file, "text/plain")}
                )

        assert upload_response.status_code == 200
        novel_id = upload_response.json()["novel_id"]

        from src.api.dependencies import get_novel_service

        service = get_novel_service()
        task_id = service.create_task(novel_id)

        with get_session_factory()() as session:
            run_repo = RunRepository(session)
            run_repo.update_run_task_fields(
                task_id,
                status="running",
                worker_id="worker-running",
                heartbeat_at=datetime.now(),
            )

        response = api_client.post(f"/api/novels/{novel_id}/tasks/{task_id}/cancel")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "cancelling"

        with get_session_factory()() as session:
            run = RunRepository(session).get_run(task_id)

        assert run is not None
        assert run["status"] == "cancelling"
        assert run["cancel_requested"] is True

    def test_cancel_task_returns_500_when_db_persistence_fails(self, api_client: TestClient):
        """测试 cancel 持久化失败时接口报错，且不会先改内存为 cancelling"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                upload_response = api_client.post(
                    "/api/novels/upload", files={"file": ("cancel_db_failure_test.txt", file, "text/plain")}
                )

        assert upload_response.status_code == 200
        novel_id = upload_response.json()["novel_id"]

        from src.api.dependencies import get_novel_service

        service = get_novel_service()
        task_id = service.create_task(novel_id)

        task_manager = TaskManager()
        task_manager.create_task(task_id, novel_id)
        api_client.app.dependency_overrides[analysis_mod.get_task_manager] = lambda: task_manager
        try:
            with patch.object(analysis_mod.RunRepository, "update_run_task_fields", side_effect=RuntimeError("db write failed")):
                response = api_client.post(f"/api/novels/{novel_id}/tasks/{task_id}/cancel")
        finally:
            api_client.app.dependency_overrides.pop(analysis_mod.get_task_manager, None)

        assert response.status_code == 500
        assert response.json()["detail"] == "任务取消持久化失败，请稍后重试"
        task_info = task_manager.get_task(task_id)
        assert task_info is not None
        assert task_info.status == analysis_mod.TaskStatus.PENDING
        assert task_info.cancel_event is not None
        assert task_info.cancel_event.is_set() is False

    def test_resume_task_clears_stale_runtime_fields_in_db(self, api_client: TestClient):
        """测试 resume 会先清空 DB 中上一轮失败留下的运行态脏字段"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                upload_response = api_client.post(
                    "/api/novels/upload", files={"file": ("resume_clear_state_test.txt", file, "text/plain")}
                )

        assert upload_response.status_code == 200
        novel_id = upload_response.json()["novel_id"]

        from src.api.dependencies import get_novel_service

        service = get_novel_service()
        task_id = service.create_task(novel_id)

        with get_session_factory()() as session:
            run_repo = RunRepository(session)
            run_repo.update_run_task_fields(
                task_id,
                status="failed",
                progress=63.5,
                stage="annotate",
                sub_stage="phase3",
                current=12,
                total=20,
                message="旧进度文案",
                error="旧错误",
                cancel_requested=True,
                completed_at=datetime.now(),
            )

        with patch.object(analysis_mod.AnalysisService, "_schedule_analysis_task", return_value=None):
            resume_response = api_client.post(f"/api/novels/{novel_id}/tasks/{task_id}/resume")

        assert resume_response.status_code == 200

        status_response = api_client.get(f"/api/novels/{novel_id}/tasks/{task_id}/status")
        assert status_response.status_code == 200
        data = status_response.json()
        assert data["status"] == "pending"
        assert data["progress"] == 0.0
        assert data["stage"] is None
        assert data["sub_stage"] is None
        assert data["message"] is None
        assert data["error"] is None

        with get_session_factory()() as session:
            run = RunRepository(session).get_run(task_id)

        assert run is not None
        assert run["cancel_requested"] is False
        assert run["completed_at"] is None

    def test_analyze_with_task_id_returns_400(self, api_client: TestClient):
        """测试旧 analyze 入口不再接受 task_id 续跑"""
        response = api_client.post("/api/novels/nonexistent/analyze", json={"task_id": "resume-me"})
        assert response.status_code == 400
        data = response.json()
        assert "resume" in data["detail"]

    def test_db_only_status_restores_persisted_message(self, api_client: TestClient):
        """测试 DB-only 状态查询可以恢复持久化的 message 文案"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                upload_response = api_client.post(
                    "/api/novels/upload", files={"file": ("status_message_test.txt", file, "text/plain")}
                )

        assert upload_response.status_code == 200
        novel_id = upload_response.json()["novel_id"]

        from src.api.dependencies import get_novel_service

        service = get_novel_service()
        task_id = service.create_task(novel_id)

        task_manager = TaskManager()
        task_manager.set_db_session_factory(lambda: get_session_factory()())
        task_manager.create_task(task_id, novel_id)
        task_manager.update_task(
            task_id,
            status=analysis_mod.TaskStatus.RUNNING,
            progress=42.0,
            stage="annotate",
            message="正在分析第 42 个分块",
        )

        status_response = api_client.get(f"/api/novels/{novel_id}/tasks/{task_id}/status")
        assert status_response.status_code == 200
        data = status_response.json()
        assert data["status"] == "running"
        assert data["message"] == "正在分析第 42 个分块"

    def test_recover_orphaned_tasks_finalizes_cancelling_tasks(self, api_client: TestClient):
        """测试启动恢复只会收口带有旧心跳的孤儿任务"""
        from src.api import main as main_mod

        session_factory = get_session_factory()
        stale_heartbeat = datetime.now() - main_mod.ORPHAN_TASK_HEARTBEAT_TIMEOUT - timedelta(minutes=1)

        with session_factory() as session:
            run_repo = RunRepository(session)
            running_run_id = run_repo.create_run(novel_id="novel-running")
            cancelling_run_id = run_repo.create_run(novel_id="novel-cancelling")
            run_repo.update_run_task_fields(
                running_run_id,
                status="running",
                worker_id="worker-a",
                heartbeat_at=stale_heartbeat,
            )
            run_repo.update_run_task_fields(
                cancelling_run_id,
                status="cancelling",
                cancel_requested=True,
                worker_id="worker-a",
                heartbeat_at=stale_heartbeat,
            )

        failed_count, cancelled_count = main_mod._recover_orphaned_tasks()

        assert failed_count == 1
        assert cancelled_count == 1

        with session_factory() as session:
            run_repo = RunRepository(session)
            running_run = run_repo.get_run(running_run_id)
            cancelling_run = run_repo.get_run(cancelling_run_id)

        assert running_run is not None
        assert running_run["status"] == "failed"
        assert cancelling_run is not None
        assert cancelling_run["status"] == "cancelled"
        assert cancelling_run["cancel_requested"] is False
        assert cancelling_run["completed_at"] is not None

    def test_recover_orphaned_tasks_skips_rows_without_worker_heartbeat(self, api_client: TestClient):
        """测试没有 worker/heartbeat 归属信息的任务不会被启动恢复误收口"""
        from src.api import main as main_mod

        session_factory = get_session_factory()

        with session_factory() as session:
            run_repo = RunRepository(session)
            running_run_id = run_repo.create_run(novel_id="novel-running-no-owner")
            cancelling_run_id = run_repo.create_run(novel_id="novel-cancelling-no-owner")
            run_repo.update_run_task_fields(running_run_id, status="running")
            run_repo.update_run_task_fields(
                cancelling_run_id,
                status="cancelling",
                cancel_requested=True,
            )

        failed_count, cancelled_count = main_mod._recover_orphaned_tasks()

        assert failed_count == 0
        assert cancelled_count == 0

        with session_factory() as session:
            run_repo = RunRepository(session)
            running_run = run_repo.get_run(running_run_id)
            cancelling_run = run_repo.get_run(cancelling_run_id)

        assert running_run is not None
        assert running_run["status"] == "running"
        assert cancelling_run is not None
        assert cancelling_run["status"] == "cancelling"
        assert cancelling_run["cancel_requested"] is True

    def test_get_task_detail_from_db_returns_none_for_unknown_task_id(self):
        """测试未知 task_id 查询详情时返回 None"""
        mock_session = MagicMock()
        mock_session.__enter__.return_value = mock_session
        mock_session.__exit__.return_value = None
        mock_session.connection.return_value = MagicMock()

        with (
            patch.object(analysis_mod, "get_session_factory", return_value=lambda: mock_session),
            patch.object(analysis_mod, "task_id_to_run_id", side_effect=TaskIDNotFoundError("not found")),
        ):
            result = analysis_mod._get_task_detail_from_db("deadbeef")

        assert result is None


class TestReanalysis:
    """测试重新分析"""

    def test_reanalyze_not_found(self, api_client: TestClient):
        """测试重新分析不存在的小说"""
        response = api_client.post("/api/novels/nonexistent/reanalyze", json={"label": "test"})
        assert response.status_code == 404

    def test_reanalyze_creates_new_version(self, api_client: TestClient):
        """测试重新分析创建新版本"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                upload_response = api_client.post(
                    "/api/novels/upload", files={"file": ("reanalyze_test.txt", file, "text/plain")}
                )

        assert upload_response.status_code == 200
        novel_id = upload_response.json()["novel_id"]

        reanalyze_response = api_client.post(f"/api/novels/{novel_id}/reanalyze", json={"label": "v2"})
        assert reanalyze_response.status_code == 200
        data = reanalyze_response.json()
        assert data["novel_id"] == novel_id
        assert "task_id" in data
        assert data["status"] == "pending"

    def test_reanalyze_auto_label(self, api_client: TestClient):
        """测试重新分析自动生成标签"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                upload_response = api_client.post(
                    "/api/novels/upload", files={"file": ("auto_label_test.txt", file, "text/plain")}
                )

        novel_id = upload_response.json()["novel_id"]

        response = api_client.post(f"/api/novels/{novel_id}/reanalyze")
        assert response.status_code == 200
        data = response.json()
        assert "task_id" in data
        assert data["status"] == "pending"


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

        await analysis_mod._cleanup_task_runtime_before_delete("task-running", task_manager)

        assert background_task.done()
        assert background_task.cancelled()

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


class TestRunRepository:
    """测试 RunRepository 的任务运行态更新"""

    def test_update_run_task_fields_can_clear_nullable_runtime_fields(self, db_session):
        """测试 update_run_task_fields 支持将 nullable 运行态字段清空为 None"""
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(novel_id="novel-1")

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
    async def test_handle_cancel_clears_cancel_requested_in_db(self, db_session):
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(novel_id="novel-1")
        run_repo.update_run_task_fields(run_id, status="cancelling", cancel_requested=True)

        task_manager = TaskManager()
        task_manager.create_task(run_id[:8], "novel-1")
        handler = AnalysisErrorHandler(
            novel_service=MagicMock(),
            task_manager=task_manager,
        )

        await handler.handle_cancel(
            task_id=run_id[:8],
            novel_id="novel-1",
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


class TestTaskManagerDbWrite:
    """测试 TaskManager 的 DB 写回使用真实 run_id"""

    def test_update_task_resolves_full_run_id_before_writing_db(self):
        """测试 8 位 task_id 写回时会先解析到完整 run_id，而不是直接精确匹配失败"""
        hex_id = uuid.uuid4().hex
        task_id = hex_id[:8]
        full_run_id = f"{task_id}-{hex_id[8:12]}-{hex_id[12:16]}-{hex_id[16:20]}-{hex_id[20:32]}"
        with get_session_factory()() as session:
            run_repo = RunRepository(session)
            run_repo.create_run(novel_id="novel-1", run_id=full_run_id)

        task_manager = TaskManager()
        task_manager.set_db_session_factory(lambda: get_session_factory()())
        task_manager.create_task(task_id, "novel-1")

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

        with get_session_factory()() as session:
            run_repo = RunRepository(session)
            run_repo.create_run(novel_id="novel-1", run_id=run_id)

        task_manager = TaskManager(worker_id="worker-test")
        task_manager.set_db_session_factory(lambda: get_session_factory()())
        task_manager.create_task(task_id, "novel-1")

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

        with get_session_factory()() as session:
            run_repo = RunRepository(session)
            run_repo.create_run(novel_id="novel-1", run_id=run_id)

        task_manager = TaskManager(worker_id="worker-heartbeat", heartbeat_interval_seconds=0.02)
        task_manager.set_db_session_factory(lambda: get_session_factory()())
        task_manager.create_task(task_id, "novel-1")

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
