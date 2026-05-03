"""
API 小说端点测试

修改时间: 2026-04-05
任务: fix-test-data-pollution
修改内容: 使用 api_client fixture 确保测试使用测试数据库

修改时间: 2026-04-22
任务: fix-novel-task-delete-consistency
修改内容: 补充小说级联删除与活动任务拦截回归测试
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text

from src.storage.db import get_session_factory
from src.storage.repositories import RunRepository


def _seed_completed_task_with_artifacts(novel_id: str, run_id: str) -> str:
    """
    为测试小说删除补一条已完成任务及其文件产物。

    创建时间: 2026-04-22
    任务: fix-novel-task-delete-consistency
    说明: 这里直接构造 chunks/global_context/graph/chunk_annotation 与日志导出文件，
          用于验证 novel 级删除会不会把 task 侧残留一起清掉。
    """
    task_id = run_id[:8]

    with get_session_factory()() as session:
        run_repo = RunRepository(session)
        run_repo.create_run(novel_id=novel_id, run_id=run_id)
        run_repo.update_run_task_fields(run_id, status="completed")
        session.execute(
            text(
                """
                INSERT INTO chunks (chunk_id, text, run_id)
                VALUES (:chunk_id, :text, :run_id)
                """
            ),
            {"chunk_id": 0, "text": "测试分块", "run_id": run_id},
        )
        session.execute(
            text(
                """
                INSERT INTO chunk_annotation (chunk_id, run_id, emotional_valence)
                VALUES (:chunk_id, :run_id, :emotional_valence)
                """
            ),
            {"chunk_id": 0, "run_id": run_id, "emotional_valence": "positive"},
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
            {"novel_id": novel_id, "novel_title": "测试小说", "run_id": run_id},
        )
        session.execute(
            text(
                """
                INSERT INTO graph_entities (run_id, canonical_name, entity_type, status)
                VALUES (:run_id, :canonical_name, :entity_type, :status)
                """
            ),
            {
                "run_id": run_id,
                "canonical_name": f"人物-{task_id}",
                "entity_type": "character",
                "status": "active",
            },
        )
        session.commit()

    log_dir = Path("logs") / run_id
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "analysis.log").write_text("test log", encoding="utf-8")
    (log_dir / "summary.json").write_text("{}", encoding="utf-8")
    output_path = Path("outputs") / f"{task_id}.json"
    output_path.write_text("{}", encoding="utf-8")
    return task_id


class TestNovelUpload:
    """测试小说上传"""

    def test_upload_txt_file(self, api_client: TestClient):
        """测试上传 .txt 文件"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                response = api_client.post("/api/novels/upload", files={"file": ("test.txt", file, "text/plain")})

        assert response.status_code == 200
        data = response.json()
        assert "novel_id" in data
        assert data["filename"] == "test.txt"
        assert data["status"] == "uploaded"

    def test_upload_invalid_file(self, api_client: TestClient):
        """测试上传无效文件"""
        response = api_client.post("/api/novels/upload", files={"file": ("test.pdf", b"content", "application/pdf")})
        assert response.status_code == 400

    def test_list_novels(self, api_client: TestClient):
        """测试列出小说"""
        response = api_client.get("/api/novels/")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert isinstance(data["items"], list)

    def test_delete_novel_cascades_tasks_and_artifacts(self, api_client: TestClient):
        """测试删除小说会级联删除其任务数据库数据与文件产物"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                upload_response = api_client.post("/api/novels/upload", files={"file": ("cascade.txt", file, "text/plain")})

        assert upload_response.status_code == 200
        novel_id = upload_response.json()["novel_id"]

        with get_session_factory()() as session:
            novel_row = session.execute(
                text("SELECT file_path FROM novels WHERE novel_id = :novel_id"),
                {"novel_id": novel_id},
            ).mappings().one()
        novel_file_path = Path(str(novel_row["file_path"]))

        task_ids = [
            _seed_completed_task_with_artifacts(novel_id, "11111111"),
            _seed_completed_task_with_artifacts(novel_id, "22222222"),
        ]

        response = api_client.delete(f"/api/novels/{novel_id}")
        assert response.status_code == 200

        with get_session_factory()() as session:
            novel_count = session.execute(
                text("SELECT COUNT(*) FROM novels WHERE novel_id = :novel_id"),
                {"novel_id": novel_id},
            ).scalar_one()
            run_count = session.execute(
                text("SELECT COUNT(*) FROM analysis_runs WHERE novel_id = :novel_id"),
                {"novel_id": novel_id},
            ).scalar_one()
            chunk_count = session.execute(
                text("SELECT COUNT(*) FROM chunks WHERE run_id IN (:run_id_1, :run_id_2)"),
                {"run_id_1": "11111111", "run_id_2": "22222222"},
            ).scalar_one()
            annotation_count = session.execute(
                text("SELECT COUNT(*) FROM chunk_annotation WHERE run_id IN (:run_id_1, :run_id_2)"),
                {"run_id_1": "11111111", "run_id_2": "22222222"},
            ).scalar_one()
            graph_count = session.execute(
                text("SELECT COUNT(*) FROM graph_entities WHERE run_id IN (:run_id_1, :run_id_2)"),
                {"run_id_1": "11111111", "run_id_2": "22222222"},
            ).scalar_one()

        assert novel_count == 0
        assert run_count == 0
        assert chunk_count == 0
        assert annotation_count == 0
        assert graph_count == 0
        assert not novel_file_path.exists()
        for task_id in task_ids:
            assert not (Path("outputs") / f"{task_id}.json").exists()
            assert not (Path("logs") / task_id).exists()

    def test_batch_delete_novels_cascades_each_novel(self, api_client: TestClient):
        """测试批量删除小说会逐个执行级联删除"""
        novel_ids: list[str] = []
        for filename in ("batch_one.txt", "batch_two.txt"):
            with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
                f.write(b"Test novel content\n" * 50)
                f.flush()

                with open(f.name, "rb") as file:
                    upload_response = api_client.post("/api/novels/upload", files={"file": (filename, file, "text/plain")})
            assert upload_response.status_code == 200
            novel_id = upload_response.json()["novel_id"]
            novel_ids.append(novel_id)
            _seed_completed_task_with_artifacts(novel_id, novel_id)

        response = api_client.post("/api/novels/batch-delete", json={"novel_ids": novel_ids})
        assert response.status_code == 200
        data = response.json()
        assert data["deleted_count"] == 2
        assert sorted(data["deleted_ids"]) == sorted(novel_ids)

        with get_session_factory()() as session:
            remaining_novels = session.execute(
                text("SELECT COUNT(*) FROM novels WHERE novel_id IN (:novel_id_1, :novel_id_2)"),
                {"novel_id_1": novel_ids[0], "novel_id_2": novel_ids[1]},
            ).scalar_one()
            remaining_runs = session.execute(
                text("SELECT COUNT(*) FROM analysis_runs WHERE novel_id IN (:novel_id_1, :novel_id_2)"),
                {"novel_id_1": novel_ids[0], "novel_id_2": novel_ids[1]},
            ).scalar_one()

        assert remaining_novels == 0
        assert remaining_runs == 0

    def test_delete_novel_rejects_active_task(self, api_client: TestClient):
        """测试删除带有活动任务的小说会被拒绝"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 50)
            f.flush()

            with open(f.name, "rb") as file:
                upload_response = api_client.post("/api/novels/upload", files={"file": ("active.txt", file, "text/plain")})

        assert upload_response.status_code == 200
        novel_id = upload_response.json()["novel_id"]

        with get_session_factory()() as session:
            task_id = RunRepository(session).create_run(novel_id=novel_id)

        response = api_client.delete(f"/api/novels/{novel_id}")
        assert response.status_code == 400
        assert task_id[:8] in response.json()["detail"]
