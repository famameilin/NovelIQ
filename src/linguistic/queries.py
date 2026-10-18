"""语言结构基础数据聚合

全部复合指标查询时计算，不落结果表；词性/词长/句式/依存比例的分母为
LTP 有效词元数或句子数，缺失或无样本时返回空值与不可用原因。
本模块返回纯 dict 载荷，响应装配留在 api 读侧。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from src.linguistic.ltp_client import POS_GROUP_MAP
from src.storage import Storage


def feature_dict(row) -> dict[str, Any]:
    """投影行 → 纯 dict（JSONB 投影列原样；列形状与旧宽表读取一致）"""
    return {
        "paragraph_id": row.paragraph_id,
        "ltp_token_count": row.ltp_token_count,
        "word_length_counts": row.word_length_counts or {},
        "pos_counts": row.pos_counts or {},
        "sentence_count": row.sentence_count,
        "sentence_pattern_counts": row.sentence_pattern_counts or {},
        "dependency_node_count": row.dependency_node_count,
        "dependency_root_count": row.dependency_root_count,
        "dependency_depth_sum": row.dependency_depth_sum,
        "dependency_depth_max": row.dependency_depth_max,
        "dependency_relation_counts": row.dependency_relation_counts or {},
        "emotion_event_count": getattr(row, "emotion_event_count", None) or 0,
        "emotion_pos_event_count": getattr(row, "emotion_pos_event_count", None) or 0,
        "emotion_neg_event_count": getattr(row, "emotion_neg_event_count", None) or 0,
        "emotion_events": getattr(row, "emotion_events", None) or [],
        "lexicon_pos_count": float(getattr(row, "lexicon_pos_count", None) or 0.0),
        "lexicon_neg_count": float(getattr(row, "lexicon_neg_count", None) or 0.0),
        "mneg_pos_count": float(getattr(row, "mneg_pos_count", None) or 0.0),
        "mneg_neg_count": float(getattr(row, "mneg_neg_count", None) or 0.0),
        "boundary_pos_score_sum": getattr(row, "boundary_pos_score_sum", None),
        "boundary_neg_score_sum": getattr(row, "boundary_neg_score_sum", None),
        "chapter_id": None,
    }


def aggregate_linguistic_features(run_id: str, session: Storage) -> dict[str, Any]:
    """
    词性/词长/句式/依存比例聚合（书级 + 章节级）

    - 词性比例、词长分布分母为 ltp_token_count（有效词元数）
    - 句式比例分母为该规则版本下的句子总数
    - 平均/最大句法深度、依存关系分布按有效句法节点守恒
    - 空段落返回零值并保留有效词元数（分母不伪造）
    """
    ling_repo = session.linguistic
    from src.linguistic.storage_projection import project_linguistic_features

    rows = project_linguistic_features(ling_repo.fetch_linguistic_sources(run_id))
    if not rows:
        return {
            "run_id": run_id,
            "paragraph_count": 0,
            "token_total": None,
            "word_length_ratios": None,
            "pos_ratios": None,
            "sentence_pattern_ratios": None,
            "avg_dependency_depth": None,
            "max_dependency_depth": None,
            "dependency_relation_ratios": None,
            "dependency_root_count": None,
            "emotion_event_count": None,
            "emotion_pos_event_count": None,
            "emotion_neg_event_count": None,
            "emotion_negated_event_count": None,
            "lexicon_pos_count": None,
            "lexicon_neg_count": None,
            "mneg_pos_count": None,
            "mneg_neg_count": None,
            "boundary_pos_score_sum": None,
            "boundary_neg_score_sum": None,
            "chapters": [],
            "emotion_event_density": None,
            "emotion_event_holders": [],
            "emotion_top_predicates": [],
            "mneg_net_delta": None,
            "lexicon_net": None,
            "mneg_net": None,
            "unavailable_reason": "linguistic_unavailable: 无语言处理完成行（语言阶段未运行）",
        }
    # 章节归属（paragraphs.chapter_id）
    paragraph_repo = session.paragraphs
    chapter_of: dict[int, int] = {
        int(row.paragraph_id): int(row.chapter_id) for row in paragraph_repo.fetch_paragraph_rows(run_id)
    }

    book = aggregate_feature_group([feature_dict(row) for row in rows])
    merged: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        feature = feature_dict(row)
        chapter_id = chapter_of.get(feature["paragraph_id"], 0)
        feature["chapter_id"] = chapter_id
        merged.setdefault(chapter_id, []).append(feature)
    chapters = [
        {"chapter_id": chapter_id, **aggregate_feature_group(group)} for chapter_id, group in sorted(merged.items())
    ]
    return {
        "run_id": run_id,
        "paragraph_count": len(rows),
        **book,
        "chapters": chapters,
        **aggregate_emotion_events(rows, book.get("token_total")),
        "unavailable_reason": None,
    }


def aggregate_feature_group(features: list[dict[str, Any]]) -> dict[str, Any]:
    """同一聚合组（书/章）内按可加充分统计量合并并计算比例"""
    token_total = sum(f["ltp_token_count"] for f in features)
    sentence_total = sum(f["sentence_count"] for f in features)
    dep_node_total = sum(f["dependency_node_count"] for f in features)

    def _merge_counts(key: str) -> dict[str, int]:
        merged: dict[str, int] = {}
        for feature in features:
            for name, count in feature.get(key, {}).items():
                merged[name] = merged.get(name, 0) + int(count)
        return merged

    total_word_lengths = _merge_counts("word_length_counts")
    total_pos = _merge_counts("pos_counts")
    total_patterns = _merge_counts("sentence_pattern_counts")
    total_relations = _merge_counts("dependency_relation_counts")

    return {
        "token_total": token_total,
        "sentence_total": sentence_total,
        "word_length_ratios": (
            {k: round(v / token_total, 6) for k, v in total_word_lengths.items()} if token_total else {}
        ),
        "pos_ratios": ({k: round(v / token_total, 6) for k, v in total_pos.items()} if token_total else {}),
        "sentence_pattern_ratios": (
            {k: round(v / sentence_total, 6) for k, v in total_patterns.items()} if sentence_total else {}
        ),
        "avg_dependency_depth": (
            round(sum(f["dependency_depth_sum"] for f in features) / dep_node_total, 6) if dep_node_total else None
        ),
        "max_dependency_depth": max((f["dependency_depth_max"] for f in features), default=None),
        "dependency_relation_ratios": (
            {k: round(v / dep_node_total, 6) for k, v in total_relations.items()} if dep_node_total else {}
        ),
        "dependency_root_count": sum(f["dependency_root_count"] for f in features),
        "emotion_event_count": sum(f["emotion_event_count"] for f in features),
        "emotion_pos_event_count": sum(f["emotion_pos_event_count"] for f in features),
        "emotion_neg_event_count": sum(f["emotion_neg_event_count"] for f in features),
        "emotion_negated_event_count": sum(
            1 for f in features for event in f["emotion_events"] if event.get("negated")
        ),
        "lexicon_pos_count": round(sum(f["lexicon_pos_count"] for f in features), 6),
        "lexicon_neg_count": round(sum(f["lexicon_neg_count"] for f in features), 6),
        "mneg_pos_count": round(sum(f["mneg_pos_count"] for f in features), 6),
        "mneg_neg_count": round(sum(f["mneg_neg_count"] for f in features), 6),
        "boundary_pos_score_sum": sum_optional(features, "boundary_pos_score_sum"),
        "boundary_neg_score_sum": sum_optional(features, "boundary_neg_score_sum"),
    }


def sum_optional(features: list[dict[str, Any]], key: str) -> float | None:
    """可空数值列求和：全 NULL 返回 None（边界未拟合），否则求和（不伪造 0）"""
    values = [feature[key] for feature in features if feature.get(key) is not None]
    if not values:
        return None
    return round(sum(float(value) for value in values), 6)


def aggregate_emotion_events(
    rows: Sequence[Any],
    token_total: int | None,
) -> dict[str, Any]:
    """书级情绪事件明细聚合（事件密度 / 持有者 × 事件 / 谓词 Top / net 对照）"""
    events = [event for row in rows for event in (feature_dict(row)["emotion_events"])]

    holders: dict[str, dict[str, int]] = {}
    predicates: dict[tuple[str, str], int] = {}
    for event in events:
        holder = event.get("holder")
        polarity = str(event.get("polarity"))
        if holder:
            bucket = holders.setdefault(str(holder), {"event_count": 0, "positive_count": 0, "negative_count": 0})
            bucket["event_count"] += 1
            bucket["positive_count" if polarity == "positive" else "negative_count"] += 1
        key = (str(event.get("predicate")), polarity)
        predicates[key] = predicates.get(key, 0) + 1

    lexicon_net = round(
        sum(float(row.lexicon_pos_count or 0.0) - float(row.lexicon_neg_count or 0.0) for row in rows), 6
    )
    mneg_net = round(sum(float(row.mneg_pos_count or 0.0) - float(row.mneg_neg_count or 0.0) for row in rows), 6)
    density = round(len(events) * 10000 / token_total, 6) if token_total and token_total > 0 else None
    return {
        "emotion_event_density": density,
        "emotion_event_holders": [
            {"holder": name, **counts}
            for name, counts in sorted(holders.items(), key=lambda item: -item[1]["event_count"])[:20]
        ],
        "emotion_top_predicates": [
            {"predicate": predicate, "polarity": polarity, "event_count": count}
            for (predicate, polarity), count in sorted(predicates.items(), key=lambda item: -item[1])[:20]
        ],
        "lexicon_net": lexicon_net,
        "mneg_net": mneg_net,
        "mneg_net_delta": round(mneg_net - lexicon_net, 6),
    }


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
            "audit_hit_count": 0,
            "metric_status": "pending_review",
            "fixed_phrase_density": None,
            "four_char_candidate_count": 0,
            "total_hits": 0,
            "unavailable_reason": "linguistic_unavailable: 无语言处理完成行，短语匹配未运行",
        }
    rows = ling_repo.fetch_phrase_hits(run_id)
    metric_hits = [row for row in rows if row.is_metric_hit]
    audit_hits = [row for row in rows if row.match_kind == "lexicon" and not row.is_metric_hit]
    four_char_candidates = [row for row in rows if row.match_kind == "four_char_candidate"]
    return {
        "run_id": run_id,
        "total_char_count": total_char_count,
        "metric_hit_count": len(metric_hits),
        "audit_hit_count": len(audit_hits),
        "metric_status": "pending_review" if audit_hits and not metric_hits else "ready",
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
            "unavailable_reason": "word2vec_unavailable: 该运行未启用 Word2Vec",
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

    逐段情绪标签的唯一落点是 analysis_assessments 的逐段情绪形状
    （record_id+paragraph_id+emotion），经章节标注产物头取得运行归属
    （产物行自带 run/章/角色）。写入前的领域校验归标注 agent，这里只按正式
    条目行返回。
    """

    rows = session.reads.linguistic_queries_fetch_paragraph_labels_1(run_id)
    return [{"paragraph_id": int(row.paragraph_id), "emotion": int(row.emotion)} for row in rows]
