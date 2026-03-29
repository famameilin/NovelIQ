import tempfile
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from src.api.main import app
from src.api.routes import analysis as analysis_mod
from src.storage.id_mapping import TaskIDNotFoundError

client = TestClient(app)


class TestAnalysis:
    def test_start_analysis_not_found(self):
        """测试分析不存在的小说"""
        response = client.post("/api/novels/nonexistent/analyze")
        assert response.status_code == 404

    def test_get_status_not_found(self):
        """测试查询不存在的小说状态"""
        response = client.get("/api/novels/nonexistent/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
        assert data["progress"] == 0.0

    def test_get_task_status_from_db_returns_pending_for_unknown_task_id(self):
        """测试未知 task_id 查询状态时返回 pending"""
        mock_session = MagicMock()
        mock_session.__enter__.return_value = mock_session
        mock_session.__exit__.return_value = None
        mock_session.connection.return_value = MagicMock()

        with (
            patch.object(analysis_mod, "get_session_factory", return_value=lambda: mock_session),
            patch.object(analysis_mod, "task_id_to_run_id", side_effect=TaskIDNotFoundError("not found")),
        ):
            status = analysis_mod._get_task_status_from_db("deadbeef")

        assert status == analysis_mod.TaskStatus.PENDING


class TestReanalysis:
    def test_reanalyze_not_found(self):
        """测试重新分析不存在的小说"""
        response = client.post(
            "/api/novels/nonexistent/reanalyze",
            json={"label": "test"}
        )
        assert response.status_code == 404

    def test_reanalyze_creates_new_version(self):
        """测试重新分析创建新版本"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                upload_response = client.post(
                    "/api/novels/upload",
                    files={"file": ("reanalyze_test.txt", file, "text/plain")}
                )

        assert upload_response.status_code == 200
        novel_id = upload_response.json()["novel_id"]

        reanalyze_response = client.post(
            f"/api/novels/{novel_id}/reanalyze",
            json={"label": "v2"}
        )
        assert reanalyze_response.status_code == 200
        data = reanalyze_response.json()
        assert data["novel_id"] == novel_id
        assert "task_id" in data
        assert data["status"] == "pending"

    def test_reanalyze_auto_label(self):
        """测试重新分析自动生成标签"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                upload_response = client.post(
                    "/api/novels/upload",
                    files={"file": ("auto_label_test.txt", file, "text/plain")}
                )

        novel_id = upload_response.json()["novel_id"]

        response = client.post(f"/api/novels/{novel_id}/reanalyze")
        assert response.status_code == 200
        data = response.json()
        assert "task_id" in data
        assert data["status"] == "pending"


class TestAnalysesList:
    def test_list_analyses_not_found(self):
        """测试查询不存在小说的分析版本列表"""
        response = client.get("/api/novels/nonexistent/tasks")
        assert response.status_code == 200
        data = response.json()
        assert data["novel_id"] == "nonexistent"
        assert data["tasks"] == []

    def test_list_analyses_after_reanalyze(self):
        """测试重新分析后查看版本列表"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                upload_response = client.post(
                    "/api/novels/upload",
                    files={"file": ("list_test.txt", file, "text/plain")}
                )

        novel_id = upload_response.json()["novel_id"]

        client.post(f"/api/novels/{novel_id}/reanalyze", json={"label": "version1"})
        client.post(f"/api/novels/{novel_id}/reanalyze", json={"label": "version2"})

        response = client.get(f"/api/novels/{novel_id}/tasks")
        assert response.status_code == 200
        data = response.json()
        assert data["novel_id"] == novel_id
        assert len(data["tasks"]) >= 2


class TestDeleteAnalysis:
    def test_delete_analysis_not_found(self):
        """测试删除不存在的分析版本"""
        response = client.delete("/api/novels/nonexistent/analyses/nonexistent_analysis")
        assert response.status_code == 404

    def test_delete_analysis_success(self):
        """测试删除分析版本成功"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                upload_response = client.post(
                    "/api/novels/upload",
                    files={"file": ("delete_test.txt", file, "text/plain")}
                )

        novel_id = upload_response.json()["novel_id"]

        reanalyze_response = client.post(
            f"/api/novels/{novel_id}/reanalyze",
            json={"label": "to_delete"}
        )
        task_id = reanalyze_response.json()["task_id"]

        delete_response = client.delete(f"/api/novels/{novel_id}/tasks/{task_id}")
        assert delete_response.status_code == 200
        data = delete_response.json()
        assert "删除成功" in data["message"] or "任务删除成功" in data["message"]
        assert data["task_id"] == task_id
