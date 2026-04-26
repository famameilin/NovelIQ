"""
测试结果 API

修改时间: 2026-03-16
修改者: TraeAI
任务: postgresql-migration-cleanup
修改内容: 更新测试以匹配当前API行为（返回空数据而非错误）

修改时间: 2026-04-05
修改者: AI Assistant
任务: fix-test-data-pollution
修改内容: 使用 api_client fixture 确保测试使用测试数据库
"""

import tempfile

from fastapi.testclient import TestClient

from src.api.main import app
from src.api.models.responses import DiagnosisResult


class TestResults:
    """测试结果端点"""

    def test_get_results_not_found(self, api_client: TestClient):
        """
        测试获取不存在任务的结果

        2026-03-13: TraeAI修改，任务refactor-api-layer-functions
        修改内容: get_results端点会先检查任务是否存在，不存在返回404

        2026-03-18: TraeAI修改，修复API参数问题
        修改内容: 将task_id改为run_id，使用完整UUID查询

        2026-03-19: TraeAI修改，任务API接口参数统一优化
        修改内容: 将run_id参数改回task_id，使用8位短UUID
        """
        response = api_client.get("/api/novels/nonexistent/results?task_id=nonexist")
        assert response.status_code == 404

    def test_get_emotion_curve_not_found(self, api_client: TestClient):
        """测试获取不存在任务的情感曲线 - 返回404"""
        response = api_client.get("/api/novels/nonexistent/emotion-curve?task_id=nonexistent")
        assert response.status_code == 404

    def test_get_rhythm_curve_not_found(self, api_client: TestClient):
        """测试获取不存在任务的节奏曲线 - 返回404"""
        response = api_client.get("/api/novels/nonexistent/rhythm-curve?task_id=nonexistent")
        assert response.status_code == 404

    def test_get_characters_not_found(self, api_client: TestClient):
        """测试获取不存在任务的人物统计 - 返回404"""
        response = api_client.get("/api/novels/nonexistent/characters?task_id=nonexistent")
        assert response.status_code == 404

    def test_get_topics_not_found(self, api_client: TestClient):
        """测试获取不存在任务的主题分布 - 返回404"""
        response = api_client.get("/api/novels/nonexistent/topics?task_id=nonexistent")
        assert response.status_code == 404

    def test_get_diagnosis_not_found(self, api_client: TestClient):
        """测试获取不存在任务的诊断结果 - 返回404"""
        response = api_client.get("/api/novels/nonexistent/diagnosis?task_id=nonexistent")
        assert response.status_code == 404

    def test_get_chunk_annotations_rejects_task_from_other_novel(self, api_client: TestClient):
        """测试 chunk_annotations 不接受属于其他小说的 task_id。"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as first_file:
            first_file.write(b"First novel content\n" * 100)
            first_file.flush()
            with open(first_file.name, "rb") as file:
                upload_response = api_client.post(
                    "/api/novels/upload",
                    files={"file": ("results_route_owner_a.txt", file, "text/plain")},
                )
        assert upload_response.status_code == 200
        first_novel_id = upload_response.json()["novel_id"]

        create_response = api_client.post(f"/api/novels/{first_novel_id}/tasks")
        assert create_response.status_code == 200
        first_task_id = create_response.json()["task_id"]

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as second_file:
            second_file.write(b"Second novel content\n" * 100)
            second_file.flush()
            with open(second_file.name, "rb") as file:
                second_upload_response = api_client.post(
                    "/api/novels/upload",
                    files={"file": ("results_route_owner_b.txt", file, "text/plain")},
                )
        assert second_upload_response.status_code == 200
        second_novel_id = second_upload_response.json()["novel_id"]

        response = api_client.get(
            f"/api/novels/{second_novel_id}/chunk-annotations?task_id={first_task_id}"
        )
        assert response.status_code == 404
        assert "不属于小说" in response.json()["detail"]

    def test_get_chunk_annotations_openapi_declares_typed_response(self):
        """
        创建时间: 2026-04-26
        创建者: Codex
        任务: phase2-strong-foreshadowing
        说明: 新增结果接口不仅要能返回数据，也要在 OpenAPI 中发布正式响应合同，
        避免前端和自动化工具只能看到 `items: {}` 的匿名数组。
        """
        schema = app.openapi()
        response_schema = schema["paths"]["/api/novels/{novel_id}/chunk-annotations"]["get"]["responses"]["200"][
            "content"
        ]["application/json"]["schema"]
        assert response_schema["type"] == "array"
        assert response_schema["items"]["$ref"] == "#/components/schemas/ChunkAnnotation"

    def test_get_diagnosis_openapi_declares_expectation_fallback_and_theme_color(self):
        """
        创建时间: 2026-04-26
        修改者: Codex
        任务: fix-phase2-setup-pool-followup-findings
        说明: diagnosis 对外合同需要明确 expectation/fallback 语义，并保留 theme_color，
              避免手写文档和响应模型再次漂移。
        """
        diagnosis_schema = DiagnosisResult.model_json_schema()
        properties = diagnosis_schema["properties"]

        assert "foreshadow_expectation" in properties
        assert "foreshadow_rate" in properties
        assert "theme_color" in properties
        assert "setup thread ledger" in properties["foreshadow_expectation"]["description"]
        assert "旧 run" in properties["foreshadow_rate"]["description"]
