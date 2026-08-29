"""Tab 级聚合端点测试

覆盖 /tabs/* 端点：
- 主题总览 tab：主题词 + 全书/章节完整分布 + TextRank 关键词一次拉取
- 实体与短语 tab：仅聚合统计，不含实体候选 span 明细（复合-only 断言）
- 无数据时 unavailable_reason 而非零值伪造；未完成 run 拒读
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.storage.repositories import ParagraphRepository
from src.storage.repositories.linguistic_repository import LinguisticRepository
from tests.support.paragraph_fixtures import (
    create_completed_run,
    create_run_with_status,
    insert_curves,
    insert_spans,
    make_curve_row,
    make_span,
)

# 与 test_topics_endpoints 相同的两章六段主题三表 fixture
_TOKENS = [10, 10, 20, 10, 10, 20]
_DISTRIBUTIONS = [[1.0, 0.0]] * 3 + [[0.0, 1.0]] * 3
_NET_DENSITY = [0.5, 0.5, 0.5, -0.5, -0.5, None]


def _insert_topic_fixture(db_session, run_id: str) -> None:
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


def _create_topic_fixture_run(db_session) -> tuple[str, str]:
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


def _mock_lda_model(monkeypatch) -> None:
    """让 /topics 的模型工件读取返回两个主题的词与标签"""
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


def test_topics_overview_tab_composites_all_sections(api_client: TestClient, db_session, monkeypatch) -> None:
    novel_id, run_id = _create_topic_fixture_run(db_session)
    _mock_lda_model(monkeypatch)

    response = api_client.get(f"/api/novels/{novel_id}/tabs/topics-overview", params={"task_id": run_id[:8]})
    assert response.status_code == 200
    body = response.json()

    # 主题词（词云数据源）
    assert {topic["topic_id"] for topic in body["topics"]} == {0, 1}
    words_by_topic = {topic["topic_id"]: topic["words"] for topic in body["topics"]}
    assert words_by_topic[0] == ["主题甲", "甲词"]
    assert body["topics"][0]["label"] == "甲"

    # 全书完整分布（K 维补零）+ 章节分布按 sequence 排序
    assert body["model"]["num_topics"] == 2
    weights = {entry["topic_id"]: entry["weight"] for entry in body["distribution"]}
    assert weights[0] == 0.5 and weights[1] == 0.5
    assert [chapter["chapter_sequence"] for chapter in body["chapters"]] == [1, 2]
    assert body["unavailable_reason"] is None

    # TextRank 关键词：结构存在且口径独立（无共现图时单独回显原因）
    assert isinstance(body["keywords"], list)
    assert body["keyword_unavailable_reason"] in (None, "no_cooccurrence: 过滤停用词后无可建图词元")


def test_topics_overview_tab_unavailable_without_model_contract(api_client: TestClient, db_session) -> None:
    novel_id, run_id = create_completed_run(db_session, chapter_texts=["甲。\n乙。"])

    response = api_client.get(f"/api/novels/{novel_id}/tabs/topics-overview", params={"task_id": run_id[:8]})
    assert response.status_code == 200
    body = response.json()
    assert body["unavailable_reason"] is not None
    assert body["distribution"] is None
    assert body["topics"] == []
    assert body["chapters"] == []
    assert body["model"] is None


def test_linguistic_entities_tab_aggregates_without_spans(api_client: TestClient, db_session) -> None:
    novel_id, run_id = _create_linguistic_fixture_run(db_session)

    response = api_client.get(f"/api/novels/{novel_id}/tabs/linguistic-entities", params={"task_id": run_id[:8]})
    assert response.status_code == 200
    body = response.json()

    assert body["count_by_type"] == {"person": 1}
    assert body["surface_top"] == [{"surface_text": "汤姆", "entity_type": "person", "count": 1}]
    assert body["total_hits"] == 2
    assert body["four_char_candidate_count"] == 1
    assert body["unavailable_reason"] is None

    # 复合-only：底层原始行字段不得出现在 tab 响应
    assert "entities" not in body
    assert "local_start_char" not in body
    assert "local_end_char" not in body
    assert "paragraph_id" not in body


def test_linguistic_entities_tab_unavailable_without_data(api_client: TestClient, db_session) -> None:
    novel_id, run_id = _create_linguistic_fixture_run(db_session, seed=False)

    response = api_client.get(f"/api/novels/{novel_id}/tabs/linguistic-entities", params={"task_id": run_id[:8]})
    assert response.status_code == 200
    body = response.json()
    assert body["count_by_type"] == {}
    assert body["surface_top"] == []
    assert body["unavailable_reason"] is not None
    assert body["total_hits"] == 0
    assert body["fixed_phrase_density"] == 0.0


def test_tabs_require_completed_run(api_client: TestClient, db_session) -> None:
    novel_id, run_id = create_run_with_status(db_session, chapter_texts=["甲。\n乙。"], status="failed")

    topics_response = api_client.get(
        f"/api/novels/{novel_id}/tabs/topics-overview", params={"task_id": run_id[:8]}
    )
    assert topics_response.status_code == 400

    linguistic_response = api_client.get(
        f"/api/novels/{novel_id}/tabs/linguistic-entities", params={"task_id": run_id[:8]}
    )
    assert linguistic_response.status_code == 400


def _make_feature_row(paragraph_id: int, *, tokens_count: int) -> dict:
    """构造 paragraph_linguistic_features 的合法插入行（paragraph_entities 外键依赖它）"""
    tokens = [
        {
            "token_index": 1,
            "text": "词",
            "local_start_char": 0,
            "local_end_char": 1,
            "pos_tag": "n",
            "pos_group": "noun",
        }
    ] * tokens_count
    return {
        "run_id": None,
        "paragraph_id": paragraph_id,
        "source_content_hash": "f" * 64,
        "ltp_token_count": tokens_count,
        "tokens": tokens,
        "word_length_counts": {"1": tokens_count},
        "pos_counts": {"noun": tokens_count},
        "sentence_count": 1,
        "sentence_pattern_counts": {"short": 1, "medium": 0, "long": 0, "compound": 0, "parallel_candidate": 0},
        "dependency_arcs": [{"dependent_index": 1, "head_index": 0, "relation": "HED"}],
        "dependency_node_count": tokens_count,
        "dependency_root_count": 1,
        "dependency_depth_sum": tokens_count - 1,
        "dependency_depth_max": 1,
        "dependency_relation_counts": {"HED": 1},
    }


def _create_linguistic_fixture_run(db_session, *, seed: bool = True) -> tuple[str, str]:
    """两段运行 + 可选的语言阶段行（特征 / 实体候选 / 短语命中）"""
    novel_id, run_id = create_completed_run(db_session, chapter_texts=["甲。\n乙。"])
    insert_spans(
        db_session,
        run_id,
        [
            make_span(
                paragraph_id=0,
                chapter_id=1,
                paragraph_index=0,
                text="甲。",
                local_start=0,
                chunk_offset=0,
                token_count=2,
            ),
            make_span(
                paragraph_id=1,
                chapter_id=1,
                paragraph_index=1,
                text="乙。",
                local_start=3,
                chunk_offset=0,
                token_count=2,
            ),
        ],
    )
    if seed:
        repo = LinguisticRepository(db_session)
        paragraph_hashes = {
            int(row.paragraph_id): row.content_hash
            for row in ParagraphRepository(db_session).fetch_paragraph_rows(run_id)
        }
        feature_rows = []
        for paragraph_id in (0, 1):
            feature_row = _make_feature_row(paragraph_id, tokens_count=4)
            feature_row["run_id"] = run_id
            feature_row["source_content_hash"] = paragraph_hashes[paragraph_id]
            feature_rows.append(feature_row)
        repo.insert_linguistic_features(run_id, feature_rows)
        repo.insert_entities(
            run_id,
            [
                {
                    "run_id": run_id,
                    "paragraph_id": 0,
                    "surface_text": "汤姆",
                    "raw_entity_type": "Nh",
                    "normalized_entity_type": "person",
                    "local_start_char": 2,
                    "local_end_char": 4,
                    "confidence": None,
                    "source_kind": "ltp",
                    "source_content_hash": paragraph_hashes[0],
                }
            ],
        )
        repo.insert_phrase_hits(
            run_id,
            [
                {
                    "run_id": run_id,
                    "paragraph_id": 0,
                    "surface_text": "刀光剑影",
                    "phrase_type": None,
                    "local_start_char": 0,
                    "local_end_char": 4,
                    "match_kind": "lexicon",
                    "lexicon_key": "fixed_phrases.txt",
                    "lexicon_version_hash": "h" * 64,
                    "is_metric_hit": False,
                    "source_content_hash": "f" * 64,
                },
                {
                    "run_id": run_id,
                    "paragraph_id": 1,
                    "surface_text": "风起云涌",
                    "phrase_type": None,
                    "local_start_char": 0,
                    "local_end_char": 4,
                    "match_kind": "four_char_candidate",
                    "lexicon_key": None,
                    "lexicon_version_hash": None,
                    "is_metric_hit": False,
                    "source_content_hash": "f" * 64,
                },
            ],
        )
        db_session.commit()
    return novel_id, run_id
