"""
GET /{novel_id}/paragraph-curves 端点测试

覆盖：
- 契约字段全集与 position 计算
- max_points 降采样：章节边界段落与 net_density 峰值强制保留、数量不超过预算
- max_points=None 返回全量
- 非 completed 状态 400
- max_points <= 0 校验 422
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.support.paragraph_fixtures import (
    create_completed_run,
    create_run_with_status,
    insert_curves,
    insert_metrics,
    insert_spans,
    insert_tension_observations,
    make_curve_row,
    make_metric_row,
    make_span,
    tension_z_for_display,
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
            chapter_id=1,
            paragraph_index=0,
            text="aaaaa",
            local_start=0,
            chunk_offset=0,
            token_count=2,
        ),
        make_span(
            paragraph_id=1,
            chapter_id=1,
            paragraph_index=1,
            text="bbbbbb",
            local_start=5,
            chunk_offset=0,
            token_count=3,
        ),
        make_span(
            paragraph_id=2,
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
            # 密度由分子÷token_count 投影：段 0 = 0.2/2 与 0.1/2，段 1 = 0.6/3 无负分子，段 2 = 1.2/4 与 0.4/4
            make_metric_row(0, token_count=2, positive_weight_sum=0.2, negative_weight_sum=0.1),
            make_metric_row(1, token_count=3, positive_weight_sum=0.6),
            make_metric_row(2, token_count=4, positive_weight_sum=1.2, negative_weight_sum=0.4),
        ],
    )
    insert_tension_observations(
        db_session,
        run_id,
        [
            (1, tension_z_for_display(0.6)),
            (2, tension_z_for_display(0.7)),
        ],
    )
    insert_curves(
        db_session,
        run_id,
        [
            # 曲线点的段落集合由真实平滑样本决定：每段至少一类样本
            make_curve_row(0, smoothed_net_density=0.05),
            make_curve_row(1, smoothed_surface_tension=0.55),
            make_curve_row(2, smoothed_net_density=0.18, smoothed_surface_tension=0.65),
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

    first, second, third = payload
    assert first["paragraph_id"] == 0
    assert first["chapter_id"] == 1
    assert first["paragraph_index"] == 0
    assert first["global_start_char"] == 0
    assert first["global_end_char"] == 5
    assert first["char_count"] == 5
    assert first["token_count"] == 2
    assert first["pos_density"] == pytest.approx(0.1)
    assert first["neg_density"] == pytest.approx(0.05)
    assert first["net_density"] == pytest.approx(0.05)
    assert first["smoothed_net_density"] == pytest.approx(0.05)
    # 没有张力 z 观测的段落读 None，不伪造 sigmoid(0)
    assert first["surface_tension"] is None
    assert first["smoothed_surface_tension"] is None
    # position = 中点 / 全书总字符数 = 2.5 / 15
    assert first["position"] == pytest.approx(2.5 / 15)

    assert second["paragraph_id"] == 1
    # 密度是「分子÷同口径 token_count」读投影：无负权重分子的段落读 0 密度
    assert second["pos_density"] == pytest.approx(0.2)
    assert second["neg_density"] == pytest.approx(0.0)
    assert second["net_density"] == pytest.approx(0.2)
    # 缺该类平滑样本的段落保留 NULL，不补零
    assert second["smoothed_net_density"] is None
    # 表面张力是对正式 z 观测的 sigmoid 读投影
    assert second["surface_tension"] == pytest.approx(0.6, abs=1e-6)
    assert second["smoothed_surface_tension"] == pytest.approx(0.55)
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
                chapter_id=chapter_id,
                paragraph_index=paragraph_index,
                text="abcde",
                local_start=paragraph_index * 5,
                chunk_offset=chunk_offsets[chapter_id],
                token_count=1,
            )
        )
    insert_spans(db_session, run_id, spans)
    insert_metrics(
        db_session,
        run_id,
        [
            # 净密度由分子÷token_count 投影：段落 50 是全书唯一峰值
            make_metric_row(
                paragraph_id,
                token_count=1,
                positive_weight_sum=1.0 if paragraph_id == 50 else 0.0,
            )
            for paragraph_id in range(100)
        ],
    )
    insert_curves(
        db_session,
        run_id,
        # 全书每段都有平滑样本行（曲线返回的段落集合由实际样本决定）
        [make_curve_row(paragraph_id, smoothed_net_density=0.0) for paragraph_id in range(100)],
    )
    return novel_id, run_id


def test_paragraph_curves_max_points_keeps_boundaries_and_peak(api_client: TestClient, db_session) -> None:
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
    assert [point["paragraph_id"] for point in payload] == sorted(point["paragraph_id"] for point in payload)


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


def test_paragraph_curves_max_points_greater_than_count_returns_all(api_client: TestClient, db_session) -> None:
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


def test_paragraph_curves_rejects_non_completed_run(api_client: TestClient, db_session) -> None:
    novel_id, run_id = create_run_with_status(db_session, chapter_texts=["第一段。"], status="running")

    response = api_client.get(
        f"/api/novels/{novel_id}/paragraph-curves",
        params={"task_id": run_id[:8]},
    )

    assert response.status_code == 400
    assert response.json()["error_type"] == "AnalysisNotCompleteError"
