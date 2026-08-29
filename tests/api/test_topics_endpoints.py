"""
主题聚合端点测试（《分析能力扩展路线图》§5.11 / D1-D3）

覆盖 GET /{novel_id}/topics 新口径与四个新端点：
- /topics/aggregate（book/chapter 分布）
- /topics/series（段落完整 K 维序列）
- /topics/shifts（JS 散度变化候选）
- /topics/emotion（主题-情感）
- 无模型契约时返回 unavailable_reason 而非零值伪造
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.storage.repositories import ParagraphRepository
from tests.support.paragraph_fixtures import (
    create_completed_run,
    create_run_with_status,
    insert_curves,
    insert_spans,
    make_curve_row,
    make_span,
)

# 章1 全主题0、章2 全主题1；inference_token_count 加权验证；段5 情感空值
_TOKENS = [10, 10, 20, 10, 10, 20]
_DISTRIBUTIONS = [[1.0, 0.0]] * 3 + [[0.0, 1.0]] * 3
_NET_DENSITY = [0.5, 0.5, 0.5, -0.5, -0.5, None]


def _insert_topic_fixture(db_session, run_id: str) -> None:
    """两章六段完整主题三表契约 + 情感曲线"""
    repo = ParagraphRepository(db_session)
    repo.insert_topic_model_run(
        run_id,
        model_key="gensim-lda",
        library_version="4.4.0",
        pipeline_version="1.0",
        num_topics=2,
        parameters={"num_topics": 2},
        dictionary_size=20,
        training_corpus_hash="a" * 64,
        training_document_count=6,
        inference_paragraph_count=6,
        artifact_key=f"models/topic/{run_id}",
        artifact_sha256="b" * 64,
    )
    repo.insert_paragraph_topic_inferences(
        run_id,
        [
            (paragraph_id, 2, _TOKENS[paragraph_id], "complete", None, 1.0, "c" * 64)
            for paragraph_id in range(6)
        ],
    )
    repo.insert_paragraph_topics(
        run_id,
        [
            (paragraph_id, topic_id, _DISTRIBUTIONS[paragraph_id][topic_id])
            for paragraph_id in range(6)
            for topic_id in range(2)
        ],
    )
    insert_curves(
        db_session,
        run_id,
        [make_curve_row(i, net_density=_NET_DENSITY[i]) for i in range(6)],
    )


def _create_fixture_run(db_session) -> tuple[str, str]:
    # 每章文本 8 字符（三个自然段各 2 字符 + 2 个换行），章2 段偏移 8
    novel_id, run_id = create_completed_run(db_session, chapter_texts=["甲。\n乙。\n丙。", "丁。\n戊。\n己。"])
    texts = ["甲。", "乙。", "丙。", "丁。", "戊。", "己。"]
    spans = []
    for paragraph_id, (chapter_id, paragraph_index) in enumerate(
        [(1, 0), (1, 1), (1, 2), (2, 0), (2, 1), (2, 2)]
    ):
        spans.append(
            make_span(
                paragraph_id=paragraph_id,
                chapter_id=chapter_id,
                paragraph_index=paragraph_index,
                text=texts[paragraph_id],
                local_start=paragraph_index * 3,
                chunk_offset=0 if chapter_id == 1 else 8,
                token_count=2,
            )
        )
    insert_spans(db_session, run_id, spans)
    _insert_topic_fixture(db_session, run_id)
    return novel_id, run_id


def test_book_aggregate_endpoint_contract(api_client: TestClient, db_session) -> None:
    novel_id, run_id = _create_fixture_run(db_session)

    response = api_client.get(
        f"/api/novels/{novel_id}/topics/aggregate", params={"level": "book", "task_id": run_id[:8]}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["level"] == "book"
    assert body["token_total"] == 80
    assert body["model"]["num_topics"] == 2
    weights = {entry["topic_id"]: entry["weight"] for entry in body["distribution"]}
    assert weights[0] == pytest.approx(0.5, abs=1e-6)
    assert weights[1] == pytest.approx(0.5, abs=1e-6)
    assert body["unavailable_reason"] is None


def test_chapter_aggregate_endpoint_orders_by_sequence(api_client: TestClient, db_session) -> None:
    novel_id, run_id = _create_fixture_run(db_session)

    response = api_client.get(
        f"/api/novels/{novel_id}/topics/aggregate", params={"level": "chapter", "task_id": run_id[:8]}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["level"] == "chapter"
    assert [c["chapter_sequence"] for c in body["chapters"]] == [1, 2]
    first = {e["topic_id"]: e["weight"] for e in body["chapters"][0]["distribution"]}
    assert first[0] == pytest.approx(1.0, abs=1e-6)


def test_series_endpoint_returns_full_k_dimension(api_client: TestClient, db_session) -> None:
    novel_id, run_id = _create_fixture_run(db_session)

    response = api_client.get(f"/api/novels/{novel_id}/topics/series", params={"task_id": run_id[:8]})
    assert response.status_code == 200
    body = response.json()
    assert body["num_topics"] == 2
    assert len(body["points"]) == 6
    # 章1 三段主题0 分布完整、按字符位置排序
    assert body["points"][0]["weights"] == pytest.approx([1.0, 0.0], abs=1e-6)
    positions = [p["start_position"] for p in body["points"]]
    assert positions == sorted(positions)


def test_shifts_endpoint_detects_abrupt_change(api_client: TestClient, db_session) -> None:
    novel_id, run_id = _create_fixture_run(db_session)

    response = api_client.get(
        f"/api/novels/{novel_id}/topics/shifts",
        params={"task_id": run_id[:8], "window_size": 3, "min_tokens_per_window": 10},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["candidates"]) == 1
    candidate = body["candidates"][0]
    assert candidate["score"] == pytest.approx(1.0, abs=1e-6)
    # 窗口 3（章1 三段落 token=40）≥ 阈值 → 候选点位于章2 首段
    assert candidate["window_token_total"] == 40
    assert body["config"]["window_size"] == 3
    assert body["config"]["score_threshold"] == 0.3


def test_emotion_endpoint_excludes_null_curves(api_client: TestClient, db_session) -> None:
    novel_id, run_id = _create_fixture_run(db_session)

    response = api_client.get(f"/api/novels/{novel_id}/topics/emotion", params={"task_id": run_id[:8]})
    assert response.status_code == 200
    body = response.json()
    by_topic = {entry["topic_id"]: entry for entry in body["emotion"]}
    assert by_topic[0]["emotion"] == pytest.approx(0.5, abs=1e-6)
    assert by_topic[1]["emotion"] == pytest.approx(-0.5, abs=1e-6)


def test_new_endpoints_unavailable_without_model_contract(api_client: TestClient, db_session) -> None:
    novel_id, run_id = create_completed_run(db_session, chapter_texts=["甲。\n乙。"])

    aggregate = api_client.get(
        f"/api/novels/{novel_id}/topics/aggregate", params={"task_id": run_id[:8]}
    )
    assert aggregate.status_code == 200
    assert aggregate.json()["unavailable_reason"] is not None
    assert aggregate.json()["distribution"] is None

    series = api_client.get(f"/api/novels/{novel_id}/topics/series", params={"task_id": run_id[:8]})
    assert series.status_code == 200
    assert series.json()["unavailable_reason"] is not None

    shifts = api_client.get(f"/api/novels/{novel_id}/topics/shifts", params={"task_id": run_id[:8]})
    assert shifts.status_code == 200
    assert shifts.json()["unavailable_reason"] is not None

    emotion = api_client.get(f"/api/novels/{novel_id}/topics/emotion", params={"task_id": run_id[:8]})
    assert emotion.status_code == 200
    assert emotion.json()["unavailable_reason"] is not None


def test_legacy_topics_endpoint_keeps_working(
    api_client: TestClient, db_session, monkeypatch
) -> None:
    """/topics 在新契约下按全书分母归一化，响应形状不变"""
    novel_id, run_id = _create_fixture_run(db_session)
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    model = MagicMock()
    model.num_topics = 2
    model.get_topic_words.side_effect = [
        [SimpleNamespace(word="主题甲"), SimpleNamespace(word="甲词")],
        [SimpleNamespace(word="主题乙"), SimpleNamespace(word="乙词")],
    ]
    model.labels = {0: "甲", 1: "乙"}
    trainer = MagicMock()
    trainer.load_model.return_value = model
    monkeypatch.setattr("src.topic.LDATrainer", lambda config: trainer)
    monkeypatch.setattr("pathlib.Path.exists", lambda self: True)

    response = api_client.get(f"/api/novels/{novel_id}/topics", params={"task_id": run_id[:8]})
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert {entry["topic_id"] for entry in body} == {0, 1}
    weights = {entry["topic_id"]: entry["weight"] for entry in body}
    assert weights[0] == pytest.approx(0.5, abs=1e-6)
    assert weights[1] == pytest.approx(0.5, abs=1e-6)


def test_topic_endpoints_require_completed_run(api_client: TestClient, db_session) -> None:
    """非可读状态运行返回 400（与既有聚合端点一致）"""
    novel_id, run_id = create_run_with_status(db_session, chapter_texts=["甲。\n乙。"], status="failed")

    response = api_client.get(
        f"/api/novels/{novel_id}/topics/aggregate", params={"task_id": run_id[:8]}
    )
    assert response.status_code == 400