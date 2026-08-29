"""语言结构基础数据聚合查询（《分析能力扩展路线图》§5.11）

全部复合指标查询时计算，不落结果表；词性/词长/句式/依存比例的分母为
LTP 有效词元数或句子数，缺失或无样本时返回空值与不可用原因。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from src.storage.repositories import ParagraphRepository
from src.storage.repositories.linguistic_repository import LinguisticRepository


def _feature_dict(row) -> dict[str, Any]:
    """ORM 行 → 纯 dict（JSONB 列原样）"""
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
        "chapter_id": None,
    }


def aggregate_linguistic_features(run_id: str, session: Session) -> dict[str, Any]:
    """
    词性/词长/句式/依存比例聚合（书级 + 章节级，§5.11）

    - 词性比例、词长分布分母为 ltp_token_count（有效词元数）
    - 句式比例分母为该规则版本下的句子总数
    - 平均/最大句法深度、依存关系分布按有效句法节点守恒
    - 空段落返回零值并保留有效词元数（分母不伪造）
    """
    ling_repo = LinguisticRepository(session)
    rows = ling_repo.fetch_linguistic_features(run_id)
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
            "chapters": [],
            "unavailable_reason": "linguistic_unavailable: 无 paragraph_linguistic_features 行（语言阶段未运行）",
        }
    # 章节归属（paragraphs.chapter_id）
    paragraph_repo = ParagraphRepository(session)
    chapter_of: dict[int, int] = {
        int(row.paragraph_id): int(row.chapter_id)
        for row in paragraph_repo.fetch_paragraph_rows(run_id)
    }

    book = _aggregate_group([_feature_dict(row) for row in rows])
    merged: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        feature = _feature_dict(row)
        chapter_id = chapter_of.get(feature["paragraph_id"], 0)
        feature["chapter_id"] = chapter_id
        merged.setdefault(chapter_id, []).append(feature)
    chapters = [
        {"chapter_id": chapter_id, **_aggregate_group(group)}
        for chapter_id, group in sorted(merged.items())
    ]
    return {
        "run_id": run_id,
        "paragraph_count": len(rows),
        **book,
        "chapters": chapters,
        "unavailable_reason": None,
    }


def _aggregate_group(features: list[dict[str, Any]]) -> dict[str, Any]:
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
    }


def fetch_entity_candidates(run_id: str, session: Session) -> dict[str, Any]:
    """LTP 实体候选列表（§5.4/§6.1 实体验证面板数据源）"""
    ling_repo = LinguisticRepository(session)
    rows = ling_repo.fetch_entities(run_id)
    if not rows:
        return {
            "run_id": run_id,
            "source_kind": "ltp",
            "entities": [],
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


def aggregate_phrase_stats(run_id: str, session: Session) -> dict[str, Any]:
    """固定短语命中统计（§5.11）：正式密度 + 四字候选数量"""
    ling_repo = LinguisticRepository(session)
    rows = ling_repo.fetch_phrase_hits(run_id)
    paragraph_repo = ParagraphRepository(session)
    total_char_count = sum(int(row.char_count) for row in paragraph_repo.fetch_paragraph_rows(run_id))
    metric_hits = [row for row in rows if row.is_metric_hit]
    four_char_candidates = [row for row in rows if row.match_kind == "four_char_candidate"]
    return {
        "run_id": run_id,
        "total_char_count": total_char_count,
        "metric_hit_count": len(metric_hits),
        "fixed_phrase_density": (
            round(len(metric_hits) * 1000 / total_char_count, 6) if total_char_count else None
        ),
        "four_char_candidate_count": len(four_char_candidates),
        "total_hits": len(rows),
        "unavailable_reason": None,
    }


def fetch_word2vec_stats(run_id: str, session: Session) -> dict[str, Any]:
    """词向量契约 + 词性覆盖率 + POS 质心（§5.6/§5.11）"""
    ling_repo = LinguisticRepository(session)
    model_run = ling_repo.fetch_word2vec_model_run(run_id)
    if model_run is None:
        return {
            "run_id": run_id,
            "model": None,
            "pos_coverage": [],
            "pos_centroids": [],
            "unavailable_reason": "word2vec_unavailable: 该运行未启用 Word2Vec",
        }
    coverage = ling_repo.fetch_pos_embedding_coverage(run_id)
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
        "artifact_scope": model_run.artifact_scope,
    }
    return {
        "run_id": run_id,
        "model": model_meta,
        "pos_coverage": pos_coverage,
        "pos_centroids": fetch_pos_centroids(run_id, session),
        "unavailable_reason": None,
    }


def fetch_pos_centroids(run_id: str, session: Session) -> list[dict[str, Any]]:
    """全书各词性组的向量质心（按词表内词数加权，§5.11）"""
    ling_repo = LinguisticRepository(session)
    rows = ling_repo.fetch_pos_embeddings(run_id)
    groups: dict[str, list[list[float]]] = {}
    weights: dict[str, list[int]] = {}
    for row in rows:
        vector = row.embedding_vector
        if row.in_vocabulary_token_count <= 0 or vector is None or len(vector) == 0:
            continue
        expanded = int(row.in_vocabulary_token_count)
        groups.setdefault(row.pos_group, []).append([float(v) for v in vector])
        weights.setdefault(row.pos_group, []).append(expanded)
    centroids: list[dict[str, Any]] = []
    for pos_group, vectors in groups.items():
        total_weight = sum(weights[pos_group])
        dim = len(vectors[0])
        weighted_sum = [0.0] * dim
        for vector, weight in zip(vectors, weights[pos_group], strict=True):
            for i in range(dim):
                weighted_sum[i] += vector[i] * weight
        centroids.append(
            {
                "pos_group": pos_group,
                "weighted_token_total": total_weight,
                "embedding_vector": [round(v / total_weight, 6) for v in weighted_sum],
            }
        )
    centroids.sort(key=lambda c: c["pos_group"])
    return centroids