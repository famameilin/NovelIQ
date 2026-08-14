"""
GET /{novel_id}/paragraph-curves 端点测试（设计文档《章节粒度分析指标重设计》§13.1）

覆盖：
- 契约字段全集与 position 计算
- max_points 降采样：章节边界段落与 net_density 峰值强制保留、数量不超过预算
- max_points=None 返回全量
- 旧 run（analysis_contract_version=NULL）409
- 非 completed 状态 400
- max_points <= 0 校验 422
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.api.models.responses import ParagraphCurvePoint
from tests.support.paragraph_fixtures import (
    create_completed_run,
    create_run_with_status,
    insert_curves,
    insert_metrics,
    insert_spans,
    make_curve_row,
    make_metric_row,
    make_span,
)


def _insert_three_paragraph_run(db_session) -> tuple[str, str]:
    """
    两章三段：
    - 章 1（chunk 0, offset 0）：段落 0（local 0..5）、段落 1（local 5..11）
    - 章 2（chunk 1, offset 12）：段落 2（local 0..4）
    全书 total_chars = 5 + 6 + 4 = 15
    """
    novel_id, run_id = create_completed_run(
        db_session,
        chapter_texts=["aaaaa\nbbbbbb", "cccc"],
    )
    spans = [
        make_span(
            paragraph_id=0,
            chunk_id=0,
            chapter_id=1,
            paragraph_index=0,
            text="aaaaa",
            local_start=0,
            chunk_offset=0,
            token_count=2,
        ),
        make_span(
            paragraph_id=1,
            chunk_id=0,
            chapter_id=1,
            paragraph_index=1,
            text="bbbbbb",
            local_start=5,
            chunk_offset=0,
            token_count=3,
        ),
        make_span(
            paragraph_id=2,
            chunk_id=1,
            chapter_id=2,
            paragraph_index=0,
            text="cccc",
            local_start=0,
            chunk_offset=12,
            token_count=4,
        ),
    ]
    insert_spans(db_session, run_id, spans)
    insert_metrics(
        db_session,
        run_id,
        [
            make_metric_row(0, token_count=2, char_count=5),
            make_metric_row(1, token_count=3, char_count=6),
            make_metric_row(2, token_count=4, char_count=4),
        ],
    )
    insert_curves(
        db_session,
        run_id,
        [
            make_curve_row(0, pos_density=0.1, neg_density=0.05, net_density=0.05),
            make_curve_row(
                1,
                pos_density=0.2,
                neg_density=None,
                net_density=None,
                smoothed_net_density=0.15,
                surface_tension=0.6,
                smoothed_surface_tension=0.55,
            ),
            make_curve_row(
                2,
                pos_density=0.3,
                neg_density=0.1,
                net_density=0.2,
                smoothed_net_density=0.18,
                surface_tension=0.7,
                smoothed_surface_tension=0.65,
            ),
        ],
    )
    return novel_id, run_id


def test_paragraph_curves_contract_fields_and_position(api_client: TestClient, db_session) -> None:
    novel_id, run_id = _insert_three_paragraph_run(db_session)

    response = api_client.get(
        f"/api/novels/{novel_id}/paragraph-curves",
        params={"task_id": run_id[:8]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 3

    expected_fields = set(ParagraphCurvePoint.model_fields)
    for point in payload:
        assert set(point) == expected_fields

    first, second, third = payload
    assert first["paragraph_id"] == 0
    assert first["chapter_id"] == 1
    assert first["paragraph_index"] == 0
    assert first["global_start_char"] == 0
    assert first["global_end_char"] == 5
    assert first["char_count"] == 5
    assert first["token_count"] == 2
    assert first["pos_density"] == 0.1
    assert first["neg_density"] == 0.05
    assert first["net_density"] == 0.05
    assert first["smoothed_net_density"] is None
    assert first["surface_tension"] is None
    assert first["smoothed_surface_tension"] is None
    # position = 中点 / 全书总字符数 = 2.5 / 15
    assert first["position"] == pytest.approx(2.5 / 15)

    assert second["paragraph_id"] == 1
    assert second["pos_density"] == 0.2
    assert second["neg_density"] is None
    assert second["net_density"] is None
    assert second["smoothed_net_density"] == 0.15
    assert second["surface_tension"] == 0.6
    assert second["smoothed_surface_tension"] == 0.55
    assert second["position"] == pytest.approx(8.0 / 15)

    assert third["paragraph_id"] == 2
    assert third["chapter_id"] == 2
    assert third["position"] == pytest.approx(14.0 / 15)


def _insert_100_paragraph_run(db_session) -> tuple[str, str]:
    """三章 100 段：章 1 段 0..32、章 2 段 33..65、章 3 段 66..99，每段 5 字符"""
    novel_id, run_id = create_completed_run(
        db_session,
        chapter_texts=["a" * 165, "b" * 165, "c" * 170],
    )
    spans = []
    chunk_offsets = {1: 0, 2: 165, 3: 330}
    for paragraph_id in range(100):
        chapter_id = 1 if paragraph_id < 33 else 2 if paragraph_id < 66 else 3
        paragraph_index = paragraph_id - (33 if chapter_id == 2 else 66 if chapter_id == 3 else 0)
        spans.append(
            make_span(
                paragraph_id=paragraph_id,
                chunk_id=chapter_id - 1,
                chapter_id=chapter_id,
                paragraph_index=paragraph_index,
                text="abcde",
                local_start=paragraph_index * 5,
                chunk_offset=chunk_offsets[chapter_id],
                token_count=1,
            )
        )
    insert_spans(db_session, run_id, spans)
    insert_curves(
        db_session,
        run_id,
        [
            # 全局 net_density 峰值在段落 50（其余为 0 或 None）
            make_curve_row(paragraph_id, net_density=1.0 if paragraph_id == 50 else 0.0)
            for paragraph_id in range(100)
        ],
    )
    return novel_id, run_id


def test_paragraph_curves_max_points_keeps_boundaries_and_peak(
    api_client: TestClient, db_session
) -> None:
    novel_id, run_id = _insert_100_paragraph_run(db_session)

    response = api_client.get(
        f"/api/novels/{novel_id}/paragraph-curves",
        params={"task_id": run_id[:8], "max_points": 10},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) <= 10
    paragraph_ids = {point["paragraph_id"] for point in payload}
    # 章节边界段落（每章首个与末个）
    assert {0, 32, 33, 65, 66, 99} <= paragraph_ids
    # net_density 全局峰值
    assert 50 in paragraph_ids
    # 返回仍按 paragraph_id 升序
    assert [point["paragraph_id"] for point in payload] == sorted(
        point["paragraph_id"] for point in payload
    )


def test_paragraph_curves_max_points_none_returns_all(api_client: TestClient, db_session) -> None:
    novel_id, run_id = _insert_100_paragraph_run(db_session)

    response = api_client.get(
        f"/api/novels/{novel_id}/paragraph-curves",
        params={"task_id": run_id[:8]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 100
    assert [point["paragraph_id"] for point in payload] == list(range(100))


def test_paragraph_curves_max_points_greater_than_count_returns_all(
    api_client: TestClient, db_session
) -> None:
    novel_id, run_id = _insert_100_paragraph_run(db_session)

    response = api_client.get(
        f"/api/novels/{novel_id}/paragraph-curves",
        params={"task_id": run_id[:8], "max_points": 500},
    )

    assert response.status_code == 200
    assert len(response.json()) == 100


def test_paragraph_curves_rejects_invalid_max_points(api_client: TestClient, db_session) -> None:
    novel_id, run_id = _insert_three_paragraph_run(db_session)

    response = api_client.get(
        f"/api/novels/{novel_id}/paragraph-curves",
        params={"task_id": run_id[:8], "max_points": 0},
    )

    assert response.status_code == 422


def test_paragraph_curves_requires_paragraph_contract(
    api_client: TestClient, db_session
) -> None:
    novel_id, run_id = create_completed_run(db_session, chapter_texts=["第一段。"])

    # 模拟旧 run：analysis_contract_version 为 NULL（§16 不兼容旧 run）
    db_session.execute(
        text("UPDATE analysis_runs SET analysis_contract_version = NULL WHERE run_id = :run_id"),
        {"run_id": run_id},
    )
    db_session.commit()

    response = api_client.get(
        f"/api/novels/{novel_id}/paragraph-curves",
        params={"task_id": run_id[:8]},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "paragraph_contract_rerun_required"
    assert "重新分析" in detail["message"]


def test_paragraph_curves_rejects_non_completed_run(api_client: TestClient, db_session) -> None:
    novel_id, run_id = create_run_with_status(db_session, chapter_texts=["第一段。"], status="running")

    response = api_client.get(
        f"/api/novels/{novel_id}/paragraph-curves",
        params={"task_id": run_id[:8]},
    )

    assert response.status_code == 400
    assert response.json()["error_type"] == "AnalysisNotCompleteError"
