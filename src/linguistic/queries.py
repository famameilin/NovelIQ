"""语言结构结果聚合与候选查询"""

from __future__ import annotations

from typing import Any

import numpy as np

from src.linguistic.ltp_client import POS_GROUP_MAP
from src.linguistic.phrase_matcher import MATCH_KIND_FOUR_CHAR, MATCH_KIND_LEXICON
from src.storage import Storage


def aggregate_linguistic_features(run_id: str, session: Storage) -> dict[str, Any]:
    """汇总正式生成的逐段统计，返回全书和章节比例"""
    payload = session.linguistic.fetch_statistics_aggregates(run_id)
    completed = payload["completed"]
    groups = payload["groups"]
    if not all(
        sum(group["word_length_counts"].values()) == group["ltp_token_count"]
        and sum(group["pos_counts"].values()) == group["ltp_token_count"]
        and sum(group["dependency_relation_counts"].values()) == group["dependency_node_count"]
        for group in groups
    ):
        raise ValueError("正式语言统计不符合计数守恒契约")
    book = next(group for group in groups if group["chapter_id"] is None)
    token_total = book["ltp_token_count"]
    lexicon_net = round(book["lexicon_pos_count"] - book["lexicon_neg_count"], 6)
    mneg_net = round(book["mneg_pos_count"] - book["mneg_neg_count"], 6)
    return {
        "run_id": run_id, "paragraph_count": completed, **_format_group(book),
        "chapters": [
            {"chapter_id": group["chapter_id"], **_format_group(group)}
            for group in sorted(
                (group for group in groups if group["chapter_id"] is not None), key=lambda group: group["chapter_id"]
            )
        ],
        "emotion_event_density": round(book["emotion_event_count"] * 10000 / token_total, 6) if token_total else None,
        "emotion_event_holders": [dict(row) for row in payload["holders"]],
        "emotion_top_predicates": [dict(row) for row in payload["predicates"]],
        "lexicon_net": lexicon_net, "mneg_net": mneg_net, "mneg_net_delta": round(mneg_net - lexicon_net, 6),
        "unavailable_reason": None,
    }


def _format_group(group: dict[str, Any]) -> dict[str, Any]:
    """按汇总分母计算比例并保留可空监督分数"""
    tokens = group["ltp_token_count"]
    sentences = group["sentence_total"]
    nodes = group["dependency_node_count"]
    result: dict[str, Any] = {
        "token_total": tokens, "sentence_total": sentences,
        "word_length_ratios": _ratios(group["word_length_counts"], tokens),
        "pos_ratios": _ratios(group["pos_counts"], tokens),
        "sentence_pattern_ratios": _ratios(group["sentence_pattern_counts"], sentences),
        "avg_dependency_depth": round(group["dependency_depth_sum"] / nodes, 6) if nodes else None,
        "max_dependency_depth": group["dependency_depth_max"],
        "dependency_relation_ratios": _ratios(group["dependency_relation_counts"], nodes),
        "dependency_root_count": group["dependency_root_count"],
    }
    for field in ("emotion_event_count", "emotion_pos_event_count", "emotion_neg_event_count",
                  "emotion_negated_event_count"):
        result[field] = group[field]
    for field in ("lexicon_pos_count", "lexicon_neg_count", "mneg_pos_count", "mneg_neg_count",
                  "boundary_pos_score_sum", "boundary_neg_score_sum"):
        value = group[field]
        result[field] = round(value, 6) if value is not None else None
    return result


def _ratios(counts: dict[str, int], denominator: int) -> dict[str, float]:
    """同一汇总组的分类计数按既定分母归一"""
    return {key: round(value / denominator, 6) for key, value in counts.items()} if denominator else {}


def fetch_entity_candidates(run_id: str, session: Storage) -> dict[str, Any]:
    """LTP 实体候选列表（实体验证面板数据源）"""
    ling_repo = session.linguistic
    from src.linguistic.ltp_client import ENTITY_TYPE_MAP

    rows = ling_repo.fetch_entities(run_id)
    for row in rows:
        row.normalized_entity_type = ENTITY_TYPE_MAP.get(str(row.raw_entity_type))
    if not rows:
        return {
            "run_id": run_id,
            "source_kind": "ltp",
            "entities": [],
            "count_by_type": {},
            "unavailable_reason": "no_entities: 无 LTP 实体候选",
        }
    by_type: dict[str, int] = {}
    entities: list[dict[str, Any]] = []
    for row in rows:
        normalized = row.normalized_entity_type or "unmapped"
        by_type[normalized] = by_type.get(normalized, 0) + 1
        entities.append(
            {
                "paragraph_id": row.paragraph_id,
                "surface_text": row.surface_text,
                "raw_entity_type": row.raw_entity_type,
                "normalized_entity_type": row.normalized_entity_type,
                "local_start_char": row.local_start_char,
                "local_end_char": row.local_end_char,
            }
        )
    return {
        "run_id": run_id,
        "source_kind": "ltp",
        "entities": entities,
        "count_by_type": by_type,
        "unavailable_reason": None,
    }


def aggregate_phrase_stats(run_id: str, session: Storage) -> dict[str, Any]:
    """固定短语命中统计：正式密度 + 四字候选数量

    前置完成事实两个都要有：语言阶段完成（language 完成行）与短语阶段完成
    （phrase_completed_at）；短语未跑与"跑完零命中"由此区分。
    """
    ling_repo = session.linguistic
    paragraph_repo = session.paragraphs
    total_char_count = sum(int(row.char_count) for row in paragraph_repo.fetch_paragraph_rows(run_id))
    if not ling_repo.has_linguistic_features(run_id) or not ling_repo.has_phrase_hits(run_id):
        return {
            "run_id": run_id,
            "total_char_count": total_char_count,
            "metric_hit_count": 0,
            "fixed_phrase_density": None,
            "four_char_candidate_count": 0,
            "total_hits": 0,
            "unavailable_reason": "linguistic_unavailable: 无语言处理完成行，短语匹配未运行",
        }
    rows = ling_repo.fetch_phrase_hits(run_id)
    metric_hits = [row for row in rows if row.match_kind == MATCH_KIND_LEXICON]
    four_char_candidates = [row for row in rows if row.match_kind == MATCH_KIND_FOUR_CHAR]
    return {
        "run_id": run_id,
        "total_char_count": total_char_count,
        "metric_hit_count": len(metric_hits),
        "fixed_phrase_density": (round(len(metric_hits) * 1000 / total_char_count, 6) if total_char_count else None),
        "four_char_candidate_count": len(four_char_candidates),
        "total_hits": len(rows),
        "unavailable_reason": None,
    }


def fetch_word2vec_stats(run_id: str, session: Storage) -> dict[str, Any]:
    """词向量契约 + 词性覆盖率 + POS 质心与组间余弦相似度"""
    ling_repo = session.linguistic
    model_run = ling_repo.fetch_word2vec_model_run(run_id)
    if model_run is None:
        return {
            "run_id": run_id,
            "model": None,
            "pos_coverage": [],
            "pos_centroids": [],
            "pos_similarity_matrix": None,
            "unavailable_reason": "word2vec_unavailable: 该运行未启用词向量",
        }
    coverage = ling_repo.fetch_pos_embedding_coverage(run_id, POS_GROUP_MAP)
    pos_coverage = [
        {
            "pos_group": row.pos_group,
            "source_token_total": int(row.source_total),
            "in_vocabulary_token_total": int(row.in_vocab_total),
            "coverage_ratio": (
                round(int(row.in_vocab_total) / int(row.source_total), 6) if int(row.source_total) else None
            ),
        }
        for row in coverage
    ]
    model_meta = {
        "embedding_dimension": model_run.embedding_dimension,
        "vocabulary_size": model_run.vocabulary_size,
        "artifact_scope": "run_owned",
    }
    centroids = fetch_pos_centroids(run_id, session)
    return {
        "run_id": run_id,
        "model": model_meta,
        "pos_coverage": pos_coverage,
        "pos_centroids": centroids,
        "pos_similarity_matrix": pos_similarity_matrix(centroids),
        "unavailable_reason": None,
    }


def pos_similarity_matrix(centroids: list[dict[str, Any]]) -> list[list[float]] | None:
    """POS 质心两两余弦相似度矩阵（行序与 centroids 一致，对称、对角线 1）

    质心少于 2 组、维度不一致或存在零向量时返回 None，不用平凡值伪造。
    """
    if len(centroids) < 2:
        return None
    dimensions = {len(centroid["embedding_vector"]) for centroid in centroids}
    if len(dimensions) != 1 or dimensions == {0}:
        return None
    vectors = np.asarray([centroid["embedding_vector"] for centroid in centroids], dtype=np.float64)
    norms = np.linalg.norm(vectors, axis=1)
    if np.any(norms == 0):
        return None
    matrix = (vectors @ vectors.T) / np.outer(norms, norms)
    return [[round(float(value), 6) for value in row] for row in matrix]


def fetch_pos_centroids(run_id: str, session: Storage) -> list[dict[str, Any]]:
    """全书各词性组的向量质心（按词表内词数加权）"""
    ling_repo = session.linguistic
    centroids: list[dict[str, Any]] = []
    for row in ling_repo.fetch_weighted_pos_embeddings(run_id):
        total_weight = int(row.weighted_token_total)
        centroids.append(
            {
                "pos_group": row.pos_group,
                "weighted_token_total": total_weight,
                "embedding_vector": [round(float(value) / total_weight, 6) for value in row.weighted_sum],
            }
        )
    return centroids


def fetch_paragraph_labels(session: Storage, run_id: str) -> list[dict[str, Any]]:
    """读取全书自选段情绪标签（段落级监督按书边界）

    逐段情绪标签的唯一落点是 agent_assessments 的逐段情绪形状
    （record_id+paragraph_id+emotion），经章节标注产物头取得运行归属
    （产物行自带 run/章/角色）。写入前的领域校验归标注 agent，这里只按正式
    条目行返回。
    """

    rows = session.reads.linguistic.list_paragraph_labels(run_id)
    return [{"paragraph_id": int(row.paragraph_id), "emotion": int(row.emotion)} for row in rows]
