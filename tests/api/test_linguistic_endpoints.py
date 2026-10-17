"""语言结构基础数据端点测试（§3.3 B/C 赛道 API 契约）

2026-10-16 3NF：种子数据只写事实列（词元区间、命中区间、候选区间），
词面/分组/类型/计量全部由读取投影补齐，因此种子坐标必须与原文自洽。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.storage.repositories.linguistic_repository import LinguisticRepository
from tests.support.paragraph_fixtures import create_completed_run, create_run_with_status, insert_spans, make_span

#: 两段原文（第二章段落起点在第 1 段文本 +\n 之后）
_PARA_TEXTS = ("汤姆刀光剑影。", "风起云涌。")
#: 段落 0 逐字符 POS（n=名词 6 个、v=动词 4 个、wp=标点 2 个）
_PARA0_POS = ["n", "n", "v", "v", "v", "v", "wp"]
_PARA1_POS = ["n", "n", "n", "n", "wp"]
_CHAPTER_TEXTS = ["\n".join(_PARA_TEXTS)]


def _tokens_of(text: str, pos_tags: list[str]) -> list[dict]:
    """按原文逐字符构造词元（索引 1 起、区间闭开、与原文切片自洽）"""
    return [
        {
            "token_index": index + 1,
            "text": char,
            "local_start_char": index,
            "local_end_char": index + 1,
            "pos_tag": pos_tags[index],
        }
        for index, char in enumerate(text)
    ]


def _make_feature_row(paragraph_id: int, *, text: str, pos_tags: list[str]) -> dict:
    """构造段落语言结构插入行（词元/依存弧/句式/观测的事实列）"""
    return {
        "paragraph_id": paragraph_id,
        "ltp_token_count": len(text),
        "tokens": _tokens_of(text, pos_tags),
        "word_length_counts": {"1": len(text)},
        "pos_counts": {},
        "sentence_count": 1,
        "sentence_pattern_counts": {"short": 1},
        # 每段两弧：词元 2 挂 1（ATT，深度 1）、词元 1 挂 ROOT（HED，深度 0）
        "dependency_arcs": [
            {"dependent_index": 2, "head_index": 1, "relation": "ATT"},
            {"dependent_index": 1, "head_index": 0, "relation": "HED"},
        ],
        "dependency_node_count": 1,
        "dependency_root_count": 1,
        "dependency_depth_sum": 1,
        "dependency_depth_max": 1,
        "dependency_relation_counts": {"HED": 1},
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
    # 运行合同先行：归一映射是版本化代码合同（不镜像成数据库表）
    from src.linguistic import ENTITY_TYPE_MAP, POS_GROUP_MAP, ltp_pipeline_contract

    pipeline_version, model_key = ltp_pipeline_contract()
    repo.ensure_ltp_contract(
        run_id,
        pipeline_version=pipeline_version,
        model_key=model_key,
        pos_mappings=POS_GROUP_MAP,
        entity_type_mappings=ENTITY_TYPE_MAP,
    )
    rows = [
        {**_make_feature_row(0, text=_PARA_TEXTS[0], pos_tags=_PARA0_POS), "run_id": run_id},
        {**_make_feature_row(1, text=_PARA_TEXTS[1], pos_tags=_PARA1_POS), "run_id": run_id},
    ]
    repo.insert_linguistic_features(run_id, rows)
    # 实体候选只存区间与原始类型；词面按原文切片、归一类型按版本映射投影
    repo.insert_entities(
        run_id,
        [
            {
                "run_id": run_id,
                "paragraph_id": 0,
                "raw_entity_type": "Nh",
                "local_start_char": 0,
                "local_end_char": 2,
            }
        ],
    )
    # 词表命中（刀光剑影）与四字候选（风起云涌）各一条；都按原文切片投影词面
    repo.insert_phrase_hits(
        run_id,
        [
            {
                "run_id": run_id,
                "paragraph_id": 0,
                "local_start_char": 2,
                "local_end_char": 6,
                "match_kind": "lexicon",
                "lexicon_key": "fixed_phrases.txt",
                "phrase_type": None,
                "is_metric_hit": False,
            },
            {
                "run_id": run_id,
                "paragraph_id": 1,
                "local_start_char": 0,
                "local_end_char": 4,
                "match_kind": "four_char_candidate",
                "lexicon_key": None,
                "phrase_type": None,
                "is_metric_hit": False,
            },
        ],
    )
    # 短语阶段完成事实（含零命中段落）：读取侧据此区分「未跑」与「跑完零命中」
    repo.mark_phrase_completed(run_id, [0, 1])
    db_session.commit()


def _create_run_with_paragraphs(db_session) -> tuple[str, str]:
    novel_id, run_id = create_completed_run(db_session, chapter_texts=_CHAPTER_TEXTS)
    second_start = len(_PARA_TEXTS[0]) + 1  # 第 1 段文本 + "\n"
    insert_spans(
        db_session,
        run_id,
        [
            make_span(
                paragraph_id=0,
                chapter_id=1,
                paragraph_index=0,
                text=_PARA_TEXTS[0],
                local_start=0,
                chunk_offset=0,
                token_count=len(_PARA_TEXTS[0]),
            ),
            make_span(
                paragraph_id=1,
                chapter_id=1,
                paragraph_index=1,
                text=_PARA_TEXTS[1],
                local_start=second_start,
                chunk_offset=0,
                token_count=len(_PARA_TEXTS[1]),
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
    # token_total 由词元行数投影；分组比例分母为有效词元数
    assert body["token_total"] == 12
    assert body["pos_ratios"]["noun"] == pytest.approx(6 / 12, abs=1e-6)
    assert body["pos_ratios"]["verb"] == pytest.approx(4 / 12, abs=1e-6)
    assert sum(body["pos_ratios"].values()) == pytest.approx(1.0, abs=1e-6)
    assert body["word_length_ratios"]["1"] == pytest.approx(1.0, abs=1e-6)
    # 每段两弧（ROOT 以空 head 表达，不建伪词元行）：深度和 2/节点 4、最大深度 1
    assert body["avg_dependency_depth"] == pytest.approx(0.5, abs=1e-6)
    assert body["max_dependency_depth"] == 1
    assert body["dependency_root_count"] == 2
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


def test_phrases_endpoint_reports_audit_only_lexicon_hits(api_client: TestClient, db_session) -> None:
    """单一固定短语词表 + 计量合同关闭：命中只做审计留痕，不计入正式密度"""
    novel_id, run_id = _create_run_with_paragraphs(db_session)
    _seed_linguistic(db_session, run_id)

    response = api_client.get(f"/api/novels/{novel_id}/linguistic/phrases", params={"task_id": run_id[:8]})
    assert response.status_code == 200
    body = response.json()
    assert body["metric_hit_count"] == 0  # 计量合同关闭：lexicon 命中不计入正式密度
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
            "window_size": 5,
            "min_count": 2,
            "epochs": 5,
            "pretrained_vocabulary_size": 100,
            "source_uri": None,
            "license_name": None,
            "training_document_count": 2,
            "training_token_count": 10,
        },
    )
    from sqlalchemy import insert as _insert

    from src.storage.models import ParagraphFeature as _M

    # source_token_count 不再是存储列：覆盖率分母由词元行 × 版本 POS 分组投影；
    # 零可用词元的分组不写行（无向量可写，缺行即零覆盖）
    db_session.execute(
        _insert(_M),
        [
            {
                "run_id": run_id,
                "paragraph_id": 0,
                "feature_code": "pos_vector:noun",
                "vector_value": [0.1] * 128,
                "in_vocabulary_token_count": 1,
            },
            {
                "run_id": run_id,
                "paragraph_id": 1,
                "feature_code": "pos_vector:noun",
                "vector_value": [0.5] * 128,
                "in_vocabulary_token_count": 3,
            },
        ],
    )
    db_session.commit()

    response = api_client.get(f"/api/novels/{novel_id}/linguistic/word2vec", params={"task_id": run_id[:8]})
    assert response.status_code == 200
    body = response.json()
    assert body["unavailable_reason"] is None
    assert body["model"]["vocabulary_size"] == 100
    assert body["pos_coverage"][0]["coverage_ratio"] == pytest.approx(4 / 6, abs=1e-6)
    assert body["pos_centroids"][0]["pos_group"] == "noun"
    assert body["pos_centroids"][0]["weighted_token_total"] == 4
    assert body["pos_centroids"][0]["embedding_vector"] == pytest.approx([0.4] * 128, abs=1e-6)
    assert len(body["pos_centroids"]) == 1


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
            "window_size": 5,
            "min_count": 2,
            "epochs": 5,
            "pretrained_vocabulary_size": 100,
            "source_uri": None,
            "license_name": None,
            "training_document_count": 2,
            "training_token_count": 10,
        },
    )
    from math import sqrt

    from sqlalchemy import insert as _insert

    from src.storage.models import ParagraphFeature as _M

    unit_x = [1.0, 0.0, 0.0, 0.0]
    unit_y = [0.0, 1.0, 0.0, 0.0]
    db_session.execute(
        _insert(_M),
        [
            {
                "run_id": run_id,
                "paragraph_id": paragraph_id,
                "feature_code": f"pos_vector:{pos_group}",
                "vector_value": vector,
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
