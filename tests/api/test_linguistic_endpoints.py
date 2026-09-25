"""语言结构基础数据端点测试（§3.3 B/C 赛道 API 契约）"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.storage.repositories.linguistic_repository import LinguisticRepository
from tests.support.paragraph_fixtures import create_completed_run, create_run_with_status, insert_spans, make_span


def _make_feature_row(
    paragraph_id: int,
    *,
    tokens_count: int,
    pos_counts: dict[str, int] | None = None,
) -> dict:
    """构造 paragraph_linguistic_features 的合法插入行（最小字段集）"""
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
        "ltp_token_count": tokens_count,
        "tokens": tokens,
        "word_length_counts": {"1": tokens_count},
        "pos_counts": pos_counts or {"noun": tokens_count},
        "sentence_count": 1,
        "sentence_pattern_counts": {"short": 1, "medium": 0, "long": 0, "compound": 0, "parallel_candidate": 0},
        "dependency_arcs": [{"dependent_index": 1, "head_index": 0, "relation": "HED"}],
        "dependency_node_count": tokens_count,
        "dependency_root_count": 1,
        "dependency_depth_sum": tokens_count - 1,
        "dependency_depth_max": 1,
        "dependency_relation_counts": {"HED": 1},
        # 2026-09-05 B 批：sdp/情绪事件列（测试种子默认空事件）
        "sdp_arcs": [],
        "emotion_events": [],
        "emotion_event_count": 0,
        "emotion_pos_event_count": 0,
        "emotion_neg_event_count": 0,
        "lexicon_pos_count": 0.0,
        "lexicon_neg_count": 0.0,
        "mneg_pos_count": 0.0,
        "mneg_neg_count": 0.0,
    }


def _seed_linguistic(db_session, run_id: str) -> None:
    repo = LinguisticRepository(db_session)
    rows = [
        _make_feature_row(0, tokens_count=4, pos_counts={"noun": 2, "verb": 2}),
        _make_feature_row(1, tokens_count=6, pos_counts={"noun": 3, "verb": 3}),
    ]
    for row in rows:
        row["run_id"] = run_id
    repo.insert_linguistic_features(run_id, rows)
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
                "is_metric_hit": False,
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
                "is_metric_hit": False,
            },
        ],
    )
    db_session.commit()


def _create_run_with_paragraphs(db_session) -> tuple[str, str]:
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
    return novel_id, run_id


def test_features_endpoint_aggregates_with_conservation(api_client: TestClient, db_session) -> None:
    novel_id, run_id = _create_run_with_paragraphs(db_session)
    _seed_linguistic(db_session, run_id)

    response = api_client.get(f"/api/novels/{novel_id}/linguistic/features", params={"task_id": run_id[:8]})
    assert response.status_code == 200
    body = response.json()
    assert body["unavailable_reason"] is None
    assert body["paragraph_count"] == 2
    assert body["token_total"] == 10
    assert body["pos_ratios"]["noun"] == pytest.approx(0.5, abs=1e-6)
    assert body["pos_ratios"]["verb"] == pytest.approx(0.5, abs=1e-6)
    assert sum(body["pos_ratios"].values()) == pytest.approx(1.0, abs=1e-6)
    assert body["avg_dependency_depth"] == 0.8
    assert body["max_dependency_depth"] == 1
    assert len(body["chapters"]) >= 1


def test_features_endpoint_unavailable_without_data(api_client: TestClient, db_session) -> None:
    novel_id, run_id = _create_run_with_paragraphs(db_session)

    response = api_client.get(f"/api/novels/{novel_id}/linguistic/features", params={"task_id": run_id[:8]})
    assert response.status_code == 200
    assert response.json()["unavailable_reason"] is not None


def test_entities_endpoint_lists_candidates(api_client: TestClient, db_session) -> None:
    novel_id, run_id = _create_run_with_paragraphs(db_session)
    _seed_linguistic(db_session, run_id)

    response = api_client.get(f"/api/novels/{novel_id}/linguistic/entities", params={"task_id": run_id[:8]})
    assert response.status_code == 200
    body = response.json()
    assert body["source_kind"] == "ltp"
    assert body["count_by_type"]["person"] == 1
    entity = body["entities"][0]
    assert entity["surface_text"] == "汤姆"
    assert entity["normalized_entity_type"] == "person"


def test_phrases_endpoint_reports_draft_lexicon_density_zero(api_client: TestClient, db_session) -> None:
    novel_id, run_id = _create_run_with_paragraphs(db_session)
    _seed_linguistic(db_session, run_id)

    response = api_client.get(f"/api/novels/{novel_id}/linguistic/phrases", params={"task_id": run_id[:8]})
    assert response.status_code == 200
    body = response.json()
    assert body["metric_hit_count"] == 0  # draft 词表不计入正式密度
    assert body["fixed_phrase_density"] == 0.0
    assert body["four_char_candidate_count"] == 1
    assert body["total_hits"] == 2


def test_word2vec_endpoint_unavailable_when_disabled(api_client: TestClient, db_session) -> None:
    novel_id, run_id = _create_run_with_paragraphs(db_session)
    _seed_linguistic(db_session, run_id)

    response = api_client.get(f"/api/novels/{novel_id}/linguistic/word2vec", params={"task_id": run_id[:8]})
    assert response.status_code == 200
    body = response.json()
    assert body["unavailable_reason"] is not None
    assert body["model"] is None


def test_word2vec_endpoint_reports_coverage_when_enabled(api_client: TestClient, db_session) -> None:
    novel_id, run_id = _create_run_with_paragraphs(db_session)
    _seed_linguistic(db_session, run_id)
    repo = LinguisticRepository(db_session)
    repo.insert_word2vec_model_run(
        run_id,
        {
            "run_id": run_id,
            "embedding_dimension": 128,
            "vocabulary_size": 100,
            "parameters": {"vector_size": 128},
            "source_uri": None,
            "license_name": None,
            "training_document_count": 2,
            "training_token_count": 10,
            "artifact_key": f"models/word2vec/{run_id}/word2vec.model",
            "artifact_scope": "run_owned",
        },
    )
    from sqlalchemy import insert as _insert

    from src.storage.models import ParagraphPosEmbedding as _M

    db_session.execute(
        _insert(_M),
        [
            {
                "run_id": run_id,
                "paragraph_id": 0,
                "pos_group": "noun",
                "embedding_vector": [0.1] * 128,
                "source_token_count": 2,
                "in_vocabulary_token_count": 1,
            }
        ],
    )
    db_session.commit()

    response = api_client.get(f"/api/novels/{novel_id}/linguistic/word2vec", params={"task_id": run_id[:8]})
    assert response.status_code == 200
    body = response.json()
    assert body["unavailable_reason"] is None
    assert body["model"]["vocabulary_size"] == 100
    assert body["pos_coverage"][0]["coverage_ratio"] == pytest.approx(0.5, abs=1e-6)
    assert body["pos_centroids"][0]["pos_group"] == "noun"


def test_word2vec_endpoint_reports_similarity_matrix(api_client: TestClient, db_session) -> None:
    """两组以上质心时返回与 pos_centroids 行序一致的余弦相似度矩阵"""
    novel_id, run_id = _create_run_with_paragraphs(db_session)
    _seed_linguistic(db_session, run_id)
    repo = LinguisticRepository(db_session)
    repo.insert_word2vec_model_run(
        run_id,
        {
            "run_id": run_id,
            "embedding_dimension": 4,
            "vocabulary_size": 100,
            "parameters": {"vector_size": 4},
            "source_uri": None,
            "license_name": None,
            "training_document_count": 2,
            "training_token_count": 10,
            "artifact_key": f"models/word2vec/{run_id}/word2vec.model",
            "artifact_scope": "run_owned",
        },
    )
    from math import sqrt

    from sqlalchemy import insert as _insert

    from src.storage.models import ParagraphPosEmbedding as _M

    unit_x = [1.0, 0.0, 0.0, 0.0]
    unit_y = [0.0, 1.0, 0.0, 0.0]
    db_session.execute(
        _insert(_M),
        [
            {
                "run_id": run_id,
                "paragraph_id": paragraph_id,
                "pos_group": pos_group,
                "embedding_vector": vector,
                "source_token_count": 2,
                "in_vocabulary_token_count": 1,
            }
            for paragraph_id, pos_group, vector in [(0, "noun", unit_x), (1, "verb", unit_y)]
        ],
    )
    db_session.commit()

    response = api_client.get(f"/api/novels/{novel_id}/linguistic/word2vec", params={"task_id": run_id[:8]})
    assert response.status_code == 200
    body = response.json()
    matrix = body["pos_similarity_matrix"]
    assert matrix is not None
    assert len(matrix) == 2 and len(matrix[0]) == 2
    assert matrix[0][0] == pytest.approx(1.0, abs=1e-6)
    assert matrix[1][1] == pytest.approx(1.0, abs=1e-6)
    assert matrix[0][1] == pytest.approx(0.0, abs=1e-6)
    assert matrix[1][0] == pytest.approx(0.0, abs=1e-6)
    # 正交单位向量加权均值仍为单位向量（权重不改变方向）
    assert body["pos_centroids"][0]["embedding_vector"] == pytest.approx(unit_x, abs=1e-6)
    assert sqrt(sum(v * v for v in body["pos_centroids"][0]["embedding_vector"])) == pytest.approx(1.0, abs=1e-6)


def test_linguistic_endpoints_require_completed_run(api_client: TestClient, db_session) -> None:

    novel_id, run_id = create_run_with_status(db_session, chapter_texts=["甲。\n乙。"], status="failed")
    response = api_client.get(f"/api/novels/{novel_id}/linguistic/features", params={"task_id": run_id[:8]})
    assert response.status_code == 400
