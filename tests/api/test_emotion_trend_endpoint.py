"""
GET /{novel_id}/emotion-trend 端点测试（设计文档《章节粒度分析指标重设计》§13.1 展示层）

覆盖：
- 契约字段全集与窗口聚合数学（覆盖率 / 池化密度）
- range 区间过滤与区间内重切窗口
- 深缩放段数不足时窗口退化为单段
- range 参数校验 422 与 window_paragraphs 5~40 钳制
- 旧 run（analysis_contract_version=NULL）409
- 非 completed 状态 400
- 无指标行的段落跳过
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.api.models.responses import EmotionTrendWindow
from tests.support.paragraph_fixtures import (
    create_completed_run,
    create_run_with_status,
    insert_metrics,
    insert_spans,
    make_metric_row,
    make_span,
)


def _insert_100_paragraph_run(db_session) -> tuple[str, str]:
    """
    三章 100 段：章 1 段 0..32、章 2 段 33..65、章 3 段 66..99，每段 5 字符。

    指标规律（token_count=2）：
    - positive_weight_sum=1 当 paragraph_id % 4 == 0（25 段）
    - negative_weight_sum=1 当 paragraph_id % 4 == 1（25 段）
    全书 total_chars = 500，段落 p 的 position = (p*5 + 2.5) / 500
    """
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
                token_count=2,
            )
        )
    insert_spans(db_session, run_id, spans)
    insert_metrics(
        db_session,
        run_id,
        [
            make_metric_row(
                paragraph_id,
                token_count=2,
                char_count=5,
                positive_weight_sum=1.0 if paragraph_id % 4 == 0 else 0.0,
                negative_weight_sum=1.0 if paragraph_id % 4 == 1 else 0.0,
            )
            for paragraph_id in range(100)
        ],
    )
    return novel_id, run_id


def test_emotion_trend_contract_fields_and_window_math(api_client: TestClient, db_session) -> None:
    novel_id, run_id = _insert_100_paragraph_run(db_session)

    response = api_client.get(
        f"/api/novels/{novel_id}/emotion-trend",
        params={"task_id": run_id[:8], "window_paragraphs": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    # 100 段 / 20 窗 = 每窗 5 段
    assert len(payload) == 20

    expected_fields = set(EmotionTrendWindow.model_fields)
    for window in payload:
        assert set(window) == expected_fields

    first = payload[0]
    assert first["window_index"] == 0
    assert first["paragraph_start"] == 0
    assert first["paragraph_end"] == 4
    assert first["chapter_start"] == 1
    assert first["chapter_end"] == 1
    assert first["paragraph_total"] == 5
    assert first["token_total"] == 10
    # 窗 0 覆盖段 0..4：pos 命中 {0,4}，neg 命中 {1}
    assert first["pos_coverage"] == pytest.approx(2 / 5)
    assert first["neg_coverage"] == pytest.approx(1 / 5)
    assert first["hit_paragraphs"] == 3
    assert first["pooled_pos_density"] == pytest.approx(2 / 10)
    assert first["pooled_neg_density"] == pytest.approx(1 / 10)
    assert first["pooled_net_density"] == pytest.approx(1 / 10)
    # position = 窗内首/末段中点 / 全书字符数
    assert first["start_position"] == pytest.approx(2.5 / 500)
    assert first["end_position"] == pytest.approx(22.5 / 500)

    last = payload[-1]
    assert last["paragraph_start"] == 95
    assert last["paragraph_end"] == 99
    assert last["chapter_start"] == 3
    assert last["chapter_end"] == 3


def test_emotion_trend_full_range_by_default(api_client: TestClient, db_session) -> None:
    novel_id, run_id = _insert_100_paragraph_run(db_session)

    response = api_client.get(
        f"/api/novels/{novel_id}/emotion-trend",
        params={"task_id": run_id[:8]},
    )

    assert response.status_code == 200
    payload = response.json()
    # 缺省 window_paragraphs=20，全书 100 段 → 5 窗
    assert len(payload) == 5
    assert payload[0]["paragraph_start"] == 0
    assert payload[-1]["paragraph_end"] == 99


def test_emotion_trend_range_rebuckets_within_selection(api_client: TestClient, db_session) -> None:
    novel_id, run_id = _insert_100_paragraph_run(db_session)

    # position 0.4~0.6 → 中点 200~300 → 段 40..59，共 20 段
    response = api_client.get(
        f"/api/novels/{novel_id}/emotion-trend",
        params={"task_id": run_id[:8], "range": "0.4,0.6", "window_paragraphs": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    # 区间内 20 段 / 每窗 5 段 = 4 窗
    assert len(payload) == 4
    assert payload[0]["paragraph_start"] == 40
    assert payload[0]["paragraph_end"] == 44
    assert payload[-1]["paragraph_start"] == 55
    assert payload[-1]["paragraph_end"] == 59
    for window in payload:
        assert window["paragraph_total"] == 5


def test_emotion_trend_deep_zoom_returns_partial_window(
    api_client: TestClient, db_session
) -> None:
    novel_id, run_id = _insert_100_paragraph_run(db_session)

    # 段 10..12 的中点分别为 52.5 / 57.5 / 62.5（/500）
    response = api_client.get(
        f"/api/novels/{novel_id}/emotion-trend",
        params={"task_id": run_id[:8], "range": "0.10,0.13", "window_paragraphs": 20},
    )

    assert response.status_code == 200
    payload = response.json()
    # 区间内仅 3 段，窗口退化为一个不足目标大小的窗口
    assert len(payload) == 1
    assert payload[0]["paragraph_start"] == 10
    assert payload[0]["paragraph_end"] == 12
    assert payload[0]["paragraph_total"] == 3


def test_emotion_trend_clamps_window_paragraphs(api_client: TestClient, db_session) -> None:
    novel_id, run_id = _insert_100_paragraph_run(db_session)

    low_response = api_client.get(
        f"/api/novels/{novel_id}/emotion-trend",
        params={"task_id": run_id[:8], "window_paragraphs": 1},
    )
    high_response = api_client.get(
        f"/api/novels/{novel_id}/emotion-trend",
        params={"task_id": run_id[:8], "window_paragraphs": 41},
    )
    assert low_response.status_code == 200
    assert high_response.status_code == 200
    assert [window["paragraph_total"] for window in low_response.json()] == [5] * 20
    assert [window["paragraph_total"] for window in high_response.json()] == [40, 40, 20]


def test_emotion_trend_rejects_invalid_range(api_client: TestClient, db_session) -> None:
    novel_id, run_id = _insert_100_paragraph_run(db_session)

    one_sided = api_client.get(
        f"/api/novels/{novel_id}/emotion-trend",
        params={"task_id": run_id[:8], "range": "0.4"},
    )
    assert one_sided.status_code == 422

    inverted = api_client.get(
        f"/api/novels/{novel_id}/emotion-trend",
        params={"task_id": run_id[:8], "range": "0.6,0.4"},
    )
    assert inverted.status_code == 422


def test_emotion_trend_requires_paragraph_contract(api_client: TestClient, db_session) -> None:
    novel_id, run_id = create_completed_run(db_session, chapter_texts=["第一段。"])

    db_session.execute(
        text("UPDATE analysis_runs SET analysis_contract_version = NULL WHERE run_id = :run_id"),
        {"run_id": run_id},
    )
    db_session.commit()

    response = api_client.get(
        f"/api/novels/{novel_id}/emotion-trend",
        params={"task_id": run_id[:8]},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "paragraph_contract_rerun_required"


def test_emotion_trend_rejects_non_completed_run(api_client: TestClient, db_session) -> None:
    novel_id, run_id = create_run_with_status(db_session, chapter_texts=["第一段。"], status="running")

    response = api_client.get(
        f"/api/novels/{novel_id}/emotion-trend",
        params={"task_id": run_id[:8]},
    )

    assert response.status_code == 400
    assert response.json()["error_type"] == "AnalysisNotCompleteError"


def test_emotion_trend_skips_paragraphs_without_metrics(api_client: TestClient, db_session) -> None:
    novel_id, run_id = create_completed_run(
        db_session,
        chapter_texts=["aaaaa\nbbbbbb", "cccc"],
    )
    insert_spans(
        db_session,
        run_id,
        [
            make_span(paragraph_id=0, chapter_id=1, paragraph_index=0, text="aaaaa",
                      local_start=0, chunk_offset=0, token_count=2),
            make_span(paragraph_id=1, chapter_id=1, paragraph_index=1, text="bbbbbb",
                      local_start=5, chunk_offset=0, token_count=3),
            make_span(paragraph_id=2, chapter_id=2, paragraph_index=0, text="cccc",
                      local_start=0, chunk_offset=12, token_count=4),
        ],
    )
    # 仅段落 0、2 有指标行（段落 1 应被跳过）
    insert_metrics(
        db_session,
        run_id,
        [
            make_metric_row(0, token_count=2, char_count=5, positive_weight_sum=2.0),
            make_metric_row(2, token_count=4, char_count=4, negative_weight_sum=1.0),
        ],
    )

    response = api_client.get(
        f"/api/novels/{novel_id}/emotion-trend",
        params={"task_id": run_id[:8], "window_paragraphs": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["paragraph_start"] == 0
    assert payload[0]["paragraph_end"] == 2
    assert payload[0]["pos_coverage"] == pytest.approx(1 / 2)
    assert payload[0]["pooled_pos_density"] == pytest.approx(2 / 6)
    assert payload[0]["neg_coverage"] == pytest.approx(1 / 2)
    assert payload[0]["pooled_neg_density"] == pytest.approx(1 / 6)
