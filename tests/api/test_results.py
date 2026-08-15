"""
测试结果 API

修改时间: 2026-03-16
任务: postgresql-migration-cleanup
修改内容: 更新测试以匹配当前API行为（返回空数据而非错误）

修改时间: 2026-04-05
任务: fix-test-data-pollution
修改内容: 使用 api_client fixture 确保测试使用测试数据库
"""

import tempfile
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.api.exceptions import DiagnosisRerunRequiredError
from src.api.main import app
from src.api.models.responses import DiagnosisResult
from src.storage.repositories import RunRepository
from tests.support.graph_snapshot_helpers import insert_graph_test_novel


class TestResults:
    """测试结果端点"""

    def test_get_results_not_found(self, api_client: TestClient):
        """
        测试获取不存在任务的结果

        2026-03-13: 修改，任务refactor-api-layer-functions
        修改内容: get_results端点会先检查任务是否存在，不存在返回404

        2026-03-18: 修改，修复API参数问题
        修改内容: 将task_id改为run_id，使用完整UUID查询

        2026-03-19: 修改，任务API接口参数统一优化
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

    def test_get_diagnosis_returns_rerun_required_for_incomplete_focus_contract(
        self,
        api_client: TestClient,
        db_session,
    ) -> None:
        novel_id = "d" + uuid.uuid4().hex[:7]
        insert_graph_test_novel(db_session, novel_id)
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path="test",
            title="Diagnosis Incomplete Contract",
        )
        run_repo.update_run_status(run_id, "completed")
        db_session.execute(
            text(
                "INSERT INTO cloud_analysis "
                "(novel_id, foreshadow_expectation, arc_scores, diagnosis, run_id) "
                "VALUES (:novel_id, :foreshadow_expectation, :arc_scores, :diagnosis, :run_id)"
            ),
            {
                "novel_id": novel_id,
                "foreshadow_expectation": 0.42,
                "arc_scores": '{"角色0": 8.2, "角色1": 7.4}',
                "diagnosis": "旧 diagnosis 行缺少 focus contract",
                "run_id": run_id,
            },
        )
        db_session.commit()

        response = api_client.get(f"/api/novels/{novel_id}/diagnosis", params={"task_id": run_id[:8]})

        assert response.status_code == 200
        payload = response.json()
        assert payload["rerun_required"] is True
        assert payload["rerun_reason"] == "focus_contract_incomplete"

    def test_get_characters_rejects_incomplete_focus_contract(self, api_client: TestClient, db_session) -> None:
        novel_id = "c" + uuid.uuid4().hex[:7]
        insert_graph_test_novel(db_session, novel_id)
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path="test",
            title="Characters Incomplete Contract",
        )
        run_repo.update_run_status(run_id, "completed")
        db_session.execute(
            text(
                "INSERT INTO cloud_analysis "
                "(novel_id, foreshadow_expectation, arc_scores, diagnosis, run_id) "
                "VALUES (:novel_id, :foreshadow_expectation, :arc_scores, :diagnosis, :run_id)"
            ),
            {
                "novel_id": novel_id,
                "foreshadow_expectation": 0.42,
                "arc_scores": '{"角色0": 8.2, "角色1": 7.4}',
                "diagnosis": "旧 diagnosis 行缺少 focus contract",
                "run_id": run_id,
            },
        )
        db_session.commit()

        response = api_client.get(f"/api/novels/{novel_id}/characters", params={"task_id": run_id[:8]})

        assert response.status_code == 409
        payload = response.json()["detail"]
        assert payload["code"] == "diagnosis_rerun_required"
        assert payload["reason"] == "focus_contract_incomplete"

    @pytest.mark.parametrize(
        ("path", "expected_status"),
        [
            ("/api/novels/{novel_id}/graph", 404),
            ("/api/novels/{novel_id}/graph/changes", 200),
        ],
    )
    def test_graph_routes_do_not_require_diagnosis_focus_contract(
        self,
        api_client: TestClient,
        db_session,
        path: str,
        expected_status: int,
    ) -> None:
        novel_id = "g" + uuid.uuid4().hex[:7]
        insert_graph_test_novel(db_session, novel_id)
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path="test",
            title="Graph Incomplete Contract",
        )
        run_repo.update_run_status(run_id, "completed")
        db_session.execute(
            text(
                "INSERT INTO cloud_analysis "
                "(novel_id, foreshadow_expectation, arc_scores, diagnosis, run_id) "
                "VALUES (:novel_id, :foreshadow_expectation, :arc_scores, :diagnosis, :run_id)"
            ),
            {
                "novel_id": novel_id,
                "foreshadow_expectation": 0.42,
                "arc_scores": '{"角色0": 8.2, "角色1": 7.4}',
                "diagnosis": "旧 diagnosis 行缺少 focus contract",
                "run_id": run_id,
            },
        )
        db_session.commit()

        response = api_client.get(path.format(novel_id=novel_id), params={"task_id": run_id[:8]})

        assert response.status_code == expected_status
        if expected_status == 200:
            assert response.json()["changes"] == []

    def test_get_results_rejects_incomplete_focus_contract(
        self,
        api_client: TestClient,
        db_session,
        monkeypatch,
    ) -> None:
        novel_id = "r" + uuid.uuid4().hex[:7]
        insert_graph_test_novel(db_session, novel_id)
        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path="test",
            title="Results Incomplete Contract",
        )
        run_repo.update_run_status(run_id, "completed")
        monkeypatch.setattr(
            "src.api.routes.results.fetch_all_results_data",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                DiagnosisRerunRequiredError(reason="focus_contract_incomplete")
            ),
        )

        response = api_client.get(f"/api/novels/{novel_id}/results", params={"task_id": run_id[:8]})

        assert response.status_code == 409
        payload = response.json()["detail"]
        assert payload["code"] == "diagnosis_rerun_required"
        assert payload["reason"] == "focus_contract_incomplete"

    def test_get_chapter_annotations_rejects_task_from_other_novel(self, api_client: TestClient):
        """测试 chapter_annotations 不接受属于其他小说的 task_id。"""
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
            f"/api/novels/{second_novel_id}/chapter-annotations?task_id={first_task_id}"
        )
        assert response.status_code == 404
        assert "不属于小说" in response.json()["detail"]

    def test_get_chapter_annotations_openapi_declares_typed_response(self):
        """
        创建时间: 2026-04-26
        任务: phase2-strong-foreshadowing
        说明: 新增结果接口不仅要能返回数据，也要在 OpenAPI 中发布正式响应合同，
        避免前端和自动化工具只能看到 `items: {}` 的匿名数组。
        """
        schema = app.openapi()
        response_schema = schema["paths"]["/api/novels/{novel_id}/chapter-annotations"]["get"]["responses"]["200"][
            "content"
        ]["application/json"]["schema"]
        assert response_schema["type"] == "array"
        assert response_schema["items"]["$ref"] == "#/components/schemas/ChapterAnnotation"

    def test_get_diagnosis_openapi_declares_expectation_fallback_and_theme_color(self):
        """
        创建时间: 2026-04-26
        任务: fix-phase2-setup-pool-followup-findings
        说明: diagnosis 对外合同需要明确 expectation/fallback 语义，并保留 theme_color，
              避免手写文档和响应模型再次漂移。
        """
        diagnosis_schema = DiagnosisResult.model_json_schema()
        properties = diagnosis_schema["properties"]

        assert "foreshadow_expectation" in properties
        assert "theme_color" in properties
        assert "setup thread ledger" in properties["foreshadow_expectation"]["description"]

    def test_get_characters_openapi_declares_typed_response(self):
        schema = app.openapi()
        response_schema = schema["paths"]["/api/novels/{novel_id}/characters"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert response_schema["type"] == "array"
        assert response_schema["items"]["$ref"] == "#/components/schemas/CharacterStats"


@pytest.mark.parametrize(
    "path",
    [
        "/api/novels/{novel_id}/chapter-annotations",
        "/api/novels/{novel_id}/paragraph-curves",
        "/api/novels/{novel_id}/chapter-metrics",
        "/api/novels/{novel_id}/topics",
        "/api/novels/{novel_id}/foreshadowing-threads",
        "/api/novels/{novel_id}/metrics/narrative-structure",
        "/api/novels/{novel_id}/metrics/emotion-stats",
        "/api/novels/{novel_id}/metrics/character-stats",
        "/api/novels/{novel_id}/metrics/style-stats",
    ],
)
def test_result_routes_reject_non_terminal_run_status(api_client: TestClient, db_session, path: str) -> None:
    novel_id = "m" + uuid.uuid4().hex[:7]
    insert_graph_test_novel(db_session, novel_id)
    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(
        novel_id=novel_id,
        source_path="test",
        title="Metrics Non Terminal Run",
    )
    run_repo.update_run_status(run_id, "running")

    response = api_client.get(path.format(novel_id=novel_id), params={"task_id": run_id[:8]})

    assert response.status_code == 400
    assert response.json()["error_type"] == "AnalysisNotCompleteError"


@pytest.mark.parametrize(
    "path",
    [
        "/api/novels/{novel_id}/diagnosis",
        "/api/novels/{novel_id}/characters",
    ],
)
def test_diagnosis_and_characters_routes_reject_non_terminal_run_status(
    api_client: TestClient,
    db_session,
    path: str,
) -> None:
    novel_id = "r" + uuid.uuid4().hex[:7]
    insert_graph_test_novel(db_session, novel_id)
    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(
        novel_id=novel_id,
        source_path="test",
        title="Results Non Terminal Run",
    )
    run_repo.update_run_status(run_id, "running")

    response = api_client.get(path.format(novel_id=novel_id), params={"task_id": run_id[:8]})

    assert response.status_code == 400
    assert response.json()["error_type"] == "AnalysisNotCompleteError"
