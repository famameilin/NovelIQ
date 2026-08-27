"""
GET /{novel_id}/metrics/global-stats 端点测试

覆盖：
- 全书聚合字段返回（total_chapters/total_chars 来自章节表，指标来自落库 global_stats）
- global_stats 未落库但章节非空时指标字段降级为 None（章节计数仍返回）
- 非 completed 状态 400 门禁
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.storage.repositories import StatsRepository
from tests.support.paragraph_fixtures import create_completed_run, create_run_with_status


def _insert_run_with_global_stats(db_session) -> tuple[str, str]:
    novel_id, run_id = create_completed_run(db_session, chapter_texts=["a" * 100, "b" * 100])
    StatsRepository(db_session).insert_global_stats(
        run_id,
        [
            ("avg_mtld", 58.4),
            ("avg_ttr", 0.62),
            ("avg_sent_len", 18.5),
            ("emotion_std", 0.18),
            ("emotion_max", 0.48),
            ("emotion_min", -0.22),
            ("rhythm_avg", 0.61),
            ("rhythm_std", 0.14),
            ("rhythm_max", 0.92),
            ("rhythm_min", 0.22),
        ],
    )
    return novel_id, run_id


def _get_global_stats(api_client, novel_id: str, run_id: str):
    return api_client.get(
        f"/api/novels/{novel_id}/metrics/global-stats",
        params={"task_id": run_id[:8]},
    )


def test_global_stats_returns_aggregated_fields(api_client: TestClient, db_session) -> None:
    novel_id, run_id = _insert_run_with_global_stats(db_session)

    resp = _get_global_stats(api_client, novel_id, run_id)

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total_chapters"] == 2
    assert payload["total_chars"] == 200
    assert payload["avg_mtld"] == 58.4
    assert payload["avg_ttr"] == 0.62
    assert payload["avg_sent_len"] == 18.5
    assert payload["emotion_std"] == 0.18
    assert payload["emotion_max"] == 0.48
    assert payload["emotion_min"] == -0.22
    assert payload["rhythm_avg"] == 0.61
    assert payload["rhythm_std"] == 0.14
    assert payload["rhythm_max"] == 0.92
    assert payload["rhythm_min"] == 0.22


def test_global_stats_without_persisted_rows_returns_none_metrics(
    api_client: TestClient,
    db_session,
) -> None:
    novel_id, run_id = create_completed_run(db_session, chapter_texts=["a" * 100])

    resp = _get_global_stats(api_client, novel_id, run_id)

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total_chapters"] == 1
    assert payload["total_chars"] == 100
    assert payload["avg_mtld"] is None
    assert payload["emotion_std"] is None


def test_global_stats_rejects_non_completed_run(api_client: TestClient, db_session) -> None:
    novel_id, run_id = create_run_with_status(
        db_session,
        chapter_texts=["a" * 100],
        status="running",
    )

    resp = _get_global_stats(api_client, novel_id, run_id)

    assert resp.status_code == 400
    assert "分析未完成" in resp.json()["detail"]
