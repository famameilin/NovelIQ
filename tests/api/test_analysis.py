"""
API 分析端点测试

修改时间: 2026-04-05
修改者: AI Assistant
任务: fix-test-data-pollution
修改内容: 使用 api_client fixture 确保测试使用测试数据库
"""

import asyncio
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.routes import analysis as analysis_mod
from src.api.services.task_manager import TaskManager
from src.storage.id_mapping import TaskIDNotFoundError


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

    def test_get_task_status_returns_404_when_db_record_missing(self, api_client: TestClient):
        """测试 DB-only 查询模式下，任务不存在时返回 404"""

        class MissingTaskNovelService:
            def get_task(self, task_id: str):
                raise RuntimeError(f"db task missing: {task_id}")

        api_client.app.dependency_overrides[analysis_mod.get_novel_service] = lambda: MissingTaskNovelService()
        try:
            response = api_client.get("/api/novels/novel-1/tasks/memory123/status")
        finally:
            api_client.app.dependency_overrides.pop(analysis_mod.get_novel_service, None)

        assert response.status_code == 404

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

    def test_analyze_with_task_id_returns_400(self, api_client: TestClient):
        """测试旧 analyze 入口不再接受 task_id 续跑"""
        response = api_client.post("/api/novels/nonexistent/analyze", json={"task_id": "resume-me"})
        assert response.status_code == 400
        data = response.json()
        assert "resume" in data["detail"]

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
