"""
API 重分析端点测试

创建时间: 2026-04-23
任务: 复杂度与耦合审查 P2 - 测试工程化
说明: 从 test_analysis.py 拆出 reanalysis 场景，降低单文件维护成本。
"""

import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api.models.requests import ReanalyzeRequest
from src.api.routes import analysis as analysis_mod
from src.storage.db import get_session_factory
from src.storage.repositories import RunRepository


class TestReanalysis:
    """测试重新分析"""

    def test_reanalyze_not_found(self, api_client: TestClient):
        """测试重新分析不存在的小说"""
        response = api_client.post("/api/novels/nonexistent/reanalyze", json={})
        assert response.status_code == 404

    def test_reanalyze_creates_new_task(self, api_client: TestClient):
        """测试重新分析创建新任务"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                upload_response = api_client.post(
                    "/api/novels/upload", files={"file": ("reanalyze_test.txt", file, "text/plain")}
                )

        assert upload_response.status_code == 200
        novel_id = upload_response.json()["novel_id"]

        reanalyze_response = api_client.post(f"/api/novels/{novel_id}/reanalyze", json={})
        assert reanalyze_response.status_code == 200
        data = reanalyze_response.json()
        assert data["novel_id"] == novel_id
        assert "task_id" in data
        assert data["status"] == "pending"

    def test_reanalyze_persists_request_payload_for_resume(self, api_client: TestClient):
        """测试 reanalyze 会持久化原始请求参数，供后续 resume/recovery 恢复语义"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                upload_response = api_client.post(
                    "/api/novels/upload", files={"file": ("reanalyze_payload_test.txt", file, "text/plain")}
                )

        assert upload_response.status_code == 200
        novel_id = upload_response.json()["novel_id"]

        request_payload = {
            "force_preprocess": True,
            "force_topic_model": True,
            "num_topics": 12,
        }
        expected_payload = ReanalyzeRequest(**request_payload).model_dump(mode="json", exclude_none=True)

        with patch.object(analysis_mod.AnalysisService, "_schedule_task_execution", return_value=None):
            reanalyze_response = api_client.post(f"/api/novels/{novel_id}/reanalyze", json=request_payload)

        assert reanalyze_response.status_code == 200
        task_id = reanalyze_response.json()["task_id"]

        with get_session_factory()() as session:
            run = RunRepository(session).get_run(task_id)

        assert run is not None
        assert run["task_kind"] == "reanalysis"
        assert run["request_payload"] == expected_payload

    def test_reanalyze_without_label(self, api_client: TestClient):
        """测试重新分析不依赖标签字段"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                upload_response = api_client.post(
                    "/api/novels/upload", files={"file": ("reanalyze_default_test.txt", file, "text/plain")}
                )

        novel_id = upload_response.json()["novel_id"]

        response = api_client.post(f"/api/novels/{novel_id}/reanalyze")
        assert response.status_code == 200
        data = response.json()
        assert "task_id" in data
        assert data["status"] == "pending"

    def test_reanalyze_request_default_num_topics_matches_settings(self) -> None:
        """
        2026-08-13 P2：ReanalyzeRequest 默认 num_topics 必须与
        settings.topic_model.num_topics 一致，无 body 与空 body 行为对齐。
        """
        from src.config import settings

        assert settings.topic_model.num_topics == 25
        assert ReanalyzeRequest().num_topics == settings.topic_model.num_topics

    def test_reanalyze_empty_body_persists_default_num_topics(self, api_client: TestClient) -> None:
        """空 body 的 reanalyze 应持久化默认 num_topics=25 的请求载荷"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                upload_response = api_client.post(
                    "/api/novels/upload", files={"file": ("reanalyze_empty_body_test.txt", file, "text/plain")}
                )

        assert upload_response.status_code == 200
        novel_id = upload_response.json()["novel_id"]

        with patch.object(analysis_mod.AnalysisService, "_schedule_task_execution", return_value=None):
            reanalyze_response = api_client.post(f"/api/novels/{novel_id}/reanalyze", json={})

        assert reanalyze_response.status_code == 200
        task_id = reanalyze_response.json()["task_id"]

        with get_session_factory()() as session:
            run = RunRepository(session).get_run(task_id)

        assert run is not None
        assert run["request_payload"] is not None
        assert run["request_payload"]["num_topics"] == 25

    def test_resume_failed_reanalysis_restores_original_request(self, api_client: TestClient):
        """测试 failed 的重分析任务 resume 时会恢复原始 force 参数与主题数"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                upload_response = api_client.post(
                    "/api/novels/upload", files={"file": ("resume_reanalyze_test.txt", file, "text/plain")}
                )

        assert upload_response.status_code == 200
        novel_id = upload_response.json()["novel_id"]

        from src.api.dependencies import get_novel_service

        service = get_novel_service()
        expected_request = ReanalyzeRequest(force_preprocess=True, force_diagnose=True, num_topics=9)
        task_id = service.create_task(
            novel_id,
            task_kind="reanalysis",
            request_payload=expected_request.model_dump(mode="json", exclude_none=True),
        )

        with get_session_factory()() as session:
            RunRepository(session).update_run_task_fields(task_id, status="failed")

        scheduled: dict[str, object] = {}

        def _record_schedule(
            self,
            scheduled_task_id: str,
            novel: dict,
            task_kind: str,
            request: ReanalyzeRequest | None = None,
        ) -> None:
            scheduled["task_id"] = scheduled_task_id
            scheduled["novel_id"] = novel["novel_id"]
            scheduled["task_kind"] = task_kind
            scheduled["request"] = request

        with patch.object(analysis_mod.AnalysisService, "_schedule_task_execution", new=_record_schedule):
            resume_response = api_client.post(f"/api/novels/{novel_id}/tasks/{task_id}/resume")

        assert resume_response.status_code == 200
        assert scheduled["task_id"] == task_id
        assert scheduled["novel_id"] == novel_id
        assert scheduled["task_kind"] == "reanalysis"
        assert isinstance(scheduled["request"], ReanalyzeRequest)
        restored_request = scheduled["request"]
        assert restored_request == expected_request
