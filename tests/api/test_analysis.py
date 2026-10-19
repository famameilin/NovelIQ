"""API 分析端点测试"""

import tempfile
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.dependencies import get_task_manager, get_task_service
from src.api.exceptions import NovelNotFoundError
from src.api.routes import analysis as analysis_mod
from src.storage import new_id
from src.storage.database_url import resolve_database_url_from_env
from src.storage.db import get_session_factory
from src.storage.repositories import RunRepository
from tests.support.analysis_factories import insert_test_novel as _insert_test_novel
from tests.support.storage_fixtures import fixture_id


class TestTestDatabaseIsolation:
    """测试后端测试环境的数据库隔离"""

    def test_get_session_factory_uses_test_database_url(self):
        """验证直接调用 get_session_factory()() 也会绑定测试数据库。"""
        expected_url = resolve_database_url_from_env("TEST_DATABASE")
        with get_session_factory()() as session:
            actual_url = session.get_bind().engine.url.render_as_string(hide_password=False)
            session.commit()
        assert actual_url == expected_url


class TestRunTimestampContract:
    """运行时间戳口径回归：无时区列统一 naive UTC，序列化带 Z 后缀"""



class TestAnalysis:
    """测试分析端点"""

    def test_create_task_not_found(self, api_client: TestClient):
        """测试创建任务时小说不存在"""
        response = api_client.post(f"/api/novels/{fixture_id(__name__, 'nonexistent')}/tasks")
        assert response.status_code == 404

    def test_resume_task_not_found(self, api_client: TestClient):
        """测试继续任务时小说不存在"""
        response = api_client.post(f"/api/novels/{fixture_id(__name__, 'nonexistent')}/tasks/fake1234/resume")
        assert response.status_code == 404

    def test_get_task_status_not_found(self, api_client: TestClient):
        """测试单任务状态接口在任务不存在时返回 404"""
        response = api_client.get(f"/api/novels/{fixture_id(__name__, 'nonexistent')}/tasks/fake1234/status")
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
        with patch.object(analysis_mod.AnalysisService, "_schedule_task_execution", return_value=None):
            create_response = api_client.post(f"/api/novels/{novel_id}/tasks")
        assert create_response.status_code == 200
        task_id = create_response.json()["task_id"]
        status_response = api_client.get(f"/api/novels/{novel_id}/tasks/{task_id}/status")
        assert status_response.status_code == 200
        data = status_response.json()
        assert data["novel_id"] == novel_id
        assert data["task_id"] == task_id


    def test_get_task_status_returns_404_when_db_record_missing(self, api_client: TestClient):
        """测试 DB-only 查询模式下，任务不存在时返回 404"""

        class MissingTaskNovelService:
            def get_task(self, task_id: str):
                raise NovelNotFoundError(message=f"db task missing: {task_id}")

        api_client.app.dependency_overrides[analysis_mod.get_task_service] = lambda: MissingTaskNovelService()
        try:
            response = api_client.get(f"/api/novels/{fixture_id(__name__, 'novel-1')}/tasks/memory123/status")
        finally:
            api_client.app.dependency_overrides.pop(analysis_mod.get_task_service, None)
        assert response.status_code == 404

    def test_get_task_status_returns_500_when_db_query_fails(self, api_client: TestClient):
        """测试 DB 查询异常不会被错误降级成 404"""

        class BrokenNovelService:
            def get_task(self, task_id: str):
                raise RuntimeError(f"db unavailable for {task_id}")

        api_client.app.dependency_overrides[analysis_mod.get_task_service] = lambda: BrokenNovelService()
        try:
            with (
                patch("src.api.main.recover_orphaned_runs", return_value=(0, 0)),
                patch("src.api.main.resume_pending_tasks", new=AsyncMock(return_value=(0, 0))),
                TestClient(api_client.app, raise_server_exceptions=False) as client,
            ):
                response = client.get(f"/api/novels/{fixture_id(__name__, 'novel-1')}/tasks/broken123/status")
        finally:
            api_client.app.dependency_overrides.pop(analysis_mod.get_task_service, None)
        assert response.status_code == 500

    def test_list_tasks_returns_500_when_db_query_fails(self, api_client: TestClient):
        """测试任务列表查询失败时返回 500，而不是伪装成空列表"""

        class BrokenNovelService:
            def get_tasks_by_novel(self, novel_id: str):
                raise RuntimeError(f"db unavailable for {novel_id}")

        api_client.app.dependency_overrides[analysis_mod.get_task_service] = lambda: BrokenNovelService()
        try:
            with (
                patch("src.api.main.recover_orphaned_runs", return_value=(0, 0)),
                patch("src.api.main.resume_pending_tasks", new=AsyncMock(return_value=(0, 0))),
                TestClient(api_client.app, raise_server_exceptions=False) as client,
            ):
                response = client.get(f"/api/novels/{fixture_id(__name__, 'novel-1')}/tasks")
        finally:
            api_client.app.dependency_overrides.pop(analysis_mod.get_task_service, None)
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

        service = get_task_service()
        task_id = service.create_task(novel_id)
        with patch.object(analysis_mod.AnalysisService, "_schedule_task_execution", return_value=None):
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
        service = get_task_service()
        with patch(
            "src.storage.access.RunAccess.create_run",
            side_effect=RuntimeError("db unavailable"),
        ):
            with pytest.raises(RuntimeError, match="db unavailable"):
                service.create_task(novel_id)

    def test_cancel_pending_task_not_in_memory_finishes_cancelled_and_can_delete(self, api_client: TestClient):
        """测试 DB-only pending 任务会直接终结为 cancelled，随后可正常删除"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()
            with open(f.name, "rb") as file:
                upload_response = api_client.post(
                    "/api/novels/upload", files={"file": ("cancel_out_of_process_test.txt", file, "text/plain")}
                )
        assert upload_response.status_code == 200
        novel_id = upload_response.json()["novel_id"]

        service = get_task_service()
        task_id = service.create_task(novel_id)
        response = api_client.post(f"/api/novels/{novel_id}/tasks/{task_id}/cancel")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "cancelled"
        with get_session_factory()() as session:
            run = RunRepository(session).get_run_by_task_id(task_id)
            session.commit()
        assert run is not None
        assert run["status"] == "cancelled"
        delete_response = api_client.post(f"/api/novels/{novel_id}/tasks/batch-delete", json={"task_ids": [task_id]})
        assert delete_response.status_code == 200
        delete_data = delete_response.json()
        assert delete_data["deleted_ids"] == [task_id]
        assert delete_data["failed_count"] == 0





    def test_resume_cancelled_task_allowed(self, api_client: TestClient):
        """验证 cancelled 任务可以继续分析并重置运行态"""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()
            with open(f.name, "rb") as file:
                upload_response = api_client.post(
                    "/api/novels/upload", files={"file": ("resume_cancelled_test.txt", file, "text/plain")}
                )
        assert upload_response.status_code == 200
        novel_id = upload_response.json()["novel_id"]

        service = get_task_service()
        task_id = service.create_task(novel_id)
        with get_session_factory()() as session:
            run_repo = RunRepository(session)
            run_repo.update_run_task_fields(run_repo.get_run_by_task_id(task_id)['run_id'], status='cancelled')
            session.commit()
        with patch.object(analysis_mod.AnalysisService, "_schedule_task_execution", return_value=None):
            resume_response = api_client.post(f"/api/novels/{novel_id}/tasks/{task_id}/resume")
        assert resume_response.status_code == 200
        status_response = api_client.get(f"/api/novels/{novel_id}/tasks/{task_id}/status")
        assert status_response.status_code == 200
        data = status_response.json()
        assert data["status"] == "pending"
        with get_session_factory()() as session:
            run = RunRepository(session).get_run_by_task_id(task_id)
            session.commit()
        assert run is not None




    @pytest.mark.asyncio
    async def test_resume_pending_tasks_reschedules_pending_runs(self, api_client: TestClient):
        """测试启动恢复会把 DB 中的 pending 任务重新调度回执行器"""
        from src.api import main as main_mod

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()
            with open(f.name, "rb") as file:
                upload_response = api_client.post(
                    "/api/novels/upload", files={"file": ("startup_pending_resume_test.txt", file, "text/plain")}
                )
        assert upload_response.status_code == 200
        novel_id = upload_response.json()["novel_id"]

        service = get_task_service()
        task_id = service.create_task(novel_id)
        scheduled_calls: list[tuple[str, str]] = []

        def _record_schedule(
            self,
            scheduled_task_id: str,
            novel: dict,
            task_kind: str,
            request=None,
            *,
            resume: bool = False,
        ) -> None:
            scheduled_calls.append((scheduled_task_id, novel["novel_id"]))

        with patch.object(analysis_mod.AnalysisService, "_schedule_task_execution", new=_record_schedule):
            scheduled_count, cancelled_count = await main_mod.resume_pending_tasks(
                get_task_service(), get_task_manager()
            )
        assert scheduled_count == len(scheduled_calls)
        assert cancelled_count == 0
        assert (task_id, novel_id) in scheduled_calls

    @pytest.mark.asyncio
    async def test_resume_pending_tasks_skips_dangling_rows_and_continues(self, api_client: TestClient):
        """测试启动恢复遇到 dangling pending 行时只跳过该任务，不影响后续有效任务恢复"""
        from src.api import main as main_mod

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()
            with open(f.name, "rb") as file:
                upload_response = api_client.post(
                    "/api/novels/upload", files={"file": ("startup_pending_skip_dangling_test.txt", file, "text/plain")}
                )
        assert upload_response.status_code == 200
        novel_id = upload_response.json()["novel_id"]

        service = get_task_service()
        valid_task_id = service.create_task(novel_id)
        skipped_task_id = "skipme01"
        skipped_novel_id = new_id()
        _insert_test_novel(skipped_novel_id)
        with get_session_factory()() as session:
            RunRepository(session).create_run(novel_id=skipped_novel_id, task_id=skipped_task_id)
            session.commit()
        scheduled_calls: list[tuple[str, str]] = []

        async def _resume_or_skip(self, resume_novel_id: str, scheduled_task_id: str) -> str:
            if scheduled_task_id == skipped_task_id:
                raise NovelNotFoundError(message=f"db task missing novel: {scheduled_task_id}")
            scheduled_calls.append((scheduled_task_id, resume_novel_id))
            return scheduled_task_id

        def _record_schedule(
            self,
            scheduled_task_id: str,
            novel: dict,
            task_kind: str,
            request=None,
            *,
            resume: bool = False,
        ) -> None:
            scheduled_calls.append((scheduled_task_id, novel["novel_id"]))

        with (
            patch.object(analysis_mod.AnalysisService, "_schedule_task_execution", new=_record_schedule),
            patch.object(analysis_mod.AnalysisService, "resume_task", new=_resume_or_skip),
        ):
            scheduled_count, cancelled_count = await main_mod.resume_pending_tasks(
                get_task_service(), get_task_manager()
            )
        assert cancelled_count == 0
        assert scheduled_count == len(scheduled_calls)
        assert (valid_task_id, novel_id) in scheduled_calls
        assert all(task_id != skipped_task_id for task_id, _ in scheduled_calls)
