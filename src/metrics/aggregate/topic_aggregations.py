"""主题聚合（《分析能力扩展路线图》§5.11 / D1、D3）。

2026-10-06 自 `src/api/services/results_queries/topic_aggregations.py` 收归读侧聚合模块；
D2 的 JS 散度与变化候选在 `algorithms.py`。全部复合结果查询时计算，不落结果表；
每个聚合携带模型契约元数据与样本量，缺失或样本不足时返回 unavailable_reason，
不用零值伪造结果。本模块返回纯 dict 载荷，响应装配留在 api 读侧。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from src.metrics.aggregate.normalization import validate_topic_aggregation_row
from src.storage.repositories import ParagraphRepository


def model_meta(dict_row: Any | None) -> dict[str, Any] | None:
    """topic_model_runs 契约行的 API 元数据视图"""
    if dict_row is None:
        return None
    return {
        "model_key": dict_row.model_key,
        "library_version": dict_row.library_version,
        "pipeline_version": dict_row.pipeline_version,
        "num_topics": dict_row.num_topics,
        "artifact_key": dict_row.artifact_key,
    }


def model_unavailable_reason(model_row: Any | None) -> str | None:
    if model_row is None:
        return "topic_inference_unavailable: 无 topic_model_runs 契约行（旧 Top-5 运行不进入聚合）"
    return None


def aggregate_book_topics(run_id: str, session: Session) -> dict[str, Any]:
    """
    全书主题分布（§5.11）：sum(topic_weight * inference_token_count) / sum(inference_token_count)

    分母从每段一行的推断状态读取，不因 K 条主题行重复放大；分布补零至
    模型契约的 num_topics 维度。
    """
    paragraph_repo = ParagraphRepository(session)
    model_row = paragraph_repo.fetch_topic_model_run(run_id)
    unavailable_reason = model_unavailable_reason(model_row)
    token_total = paragraph_repo.fetch_topic_inference_total(run_id)

    distribution: list[dict[str, float]] | None = None
    if not unavailable_reason and token_total is not None:
        assert model_row is not None
        if token_total <= 0:
            unavailable_reason = "empty_inference: 无有效推断 token（每段一行推断状态缺失或为零）"
        else:
            agg_rows = paragraph_repo.fetch_paragraph_topics_agg(run_id)
            weights = {int(row.topic_id): float(row.weighted_total) for row in agg_rows}
            distribution = [
                {"topic_id": topic_id, "weight": round(weights.get(topic_id, 0.0) / token_total, 6)}
                for topic_id in range(model_row.num_topics)
            ]

    result: dict[str, Any] = {
        "run_id": run_id,
        "level": "book",
        "model": model_meta(model_row),
        "token_total": token_total,
        "distribution": distribution,
        "unavailable_reason": unavailable_reason,
    }
    return result


def aggregate_chapter_topics(run_id: str, session: Session) -> dict[str, Any]:
    """
    章节主题分布（§5.11）：每章 sum(w * t) / 该章段落推断 token 和

    章节边界用 paragraphs.chapter_id 关联 chapters 并按 chapters.sequence
    排序，不使用段落列表下标推断章节。
    """
    paragraph_repo = ParagraphRepository(session)
    model_row = paragraph_repo.fetch_topic_model_run(run_id)
    unavailable_reason = model_unavailable_reason(model_row)
    if unavailable_reason:
        return {
            "run_id": run_id,
            "model": None,
            "chapters": [],
            "unavailable_reason": unavailable_reason,
        }

    assert model_row is not None
    agg_rows = paragraph_repo.fetch_chapter_topic_aggregates(run_id)
    token_rows = paragraph_repo.fetch_chapter_inference_totals(run_id)

    chapters: dict[int, dict[str, Any]] = {
        int(row.chapter_id): {
            "chapter_id": int(row.chapter_id),
            "chapter_sequence": int(row.sequence),
            "chapter_title": row.title,
            "token_total": int(row.token_total or 0),
            "distribution": {},
        }
        for row in token_rows
    }
    for row in agg_rows:
        chapter_id = int(row.chapter_id)
        entry = chapters.setdefault(
            chapter_id,
            {
                "chapter_id": chapter_id,
                "chapter_sequence": int(row.sequence),
                "chapter_title": row.title,
                "token_total": 0,
                "distribution": {},
            },
        )
        entry["distribution"][int(row.topic_id)] = float(row.weighted_total)

    num_topics = model_row.num_topics
    result: list[dict[str, Any]] = []
    for chapter_id in sorted(chapters, key=lambda cid: chapters[cid]["chapter_sequence"]):
        entry = chapters[chapter_id]
        token_total = entry["token_total"]
        distribution: list[dict[str, float]] | None = None
        if token_total > 0:
            distribution = [
                {"topic_id": topic_id, "weight": round(entry["distribution"].get(topic_id, 0.0) / token_total, 6)}
                for topic_id in range(num_topics)
            ]
        result.append(
            {
                "chapter_id": entry["chapter_id"],
                "chapter_sequence": entry["chapter_sequence"],
                "chapter_title": entry["chapter_title"],
                "token_total": token_total,
                "distribution": distribution,
            }
        )
    return {
        "run_id": run_id,
        "model": model_meta(model_row),
        "chapters": result,
        "unavailable_reason": None,
    }


def fetch_paragraph_topic_series(run_id: str, session: Session) -> dict[str, Any]:
    """
    段落主题序列（D1）：按真实字符位置输出完整 K 维主题权重

    横轴使用 global_start_char / global_end_char；top_n 只属于前端展示裁剪，
    本接口始终返回完整分布。
    """
    paragraph_repo = ParagraphRepository(session)
    model_row = paragraph_repo.fetch_topic_model_run(run_id)
    unavailable_reason = model_unavailable_reason(model_row)
    if unavailable_reason:
        return {
            "run_id": run_id,
            "model": None,
            "num_topics": None,
            "points": [],
            "unavailable_reason": unavailable_reason,
        }

    assert model_row is not None
    rows = paragraph_repo.fetch_paragraph_topic_rows(run_id)
    num_topics = model_row.num_topics
    points: dict[int, dict[str, Any]] = {}
    for row in rows:
        paragraph_id = int(row.paragraph_id)
        point = points.setdefault(
            paragraph_id,
            {
                "paragraph_id": paragraph_id,
                "chapter_id": int(row.chapter_id),
                "chapter_sequence": int(row.sequence),
                "start_position": int(row.global_start_char),
                "token_count": int(row.inference_token_count),
                "weights": [0.0] * num_topics,
            },
        )
        point["weights"][int(row.topic_id)] = float(row.topic_weight)

    ordered = sorted(points.values(), key=lambda p: (p["start_position"], p["paragraph_id"]))
    return {
        "run_id": run_id,
        "model": model_meta(model_row),
        "num_topics": num_topics,
        "points": ordered,
        "unavailable_reason": None,
    }


def compute_topic_emotion(run_id: str, session: Session) -> dict[str, Any]:
    """
    主题-情感统计（D3）：sum(weight * token * net_density) / sum(weight * token)

    情感输入使用 paragraph_curves.net_density 原始值；空值段落在 SQL 层
    同时从分子分母排除；权重和为零时返回空值并记录原因。
    """
    paragraph_repo = ParagraphRepository(session)
    model_row = paragraph_repo.fetch_topic_model_run(run_id)
    unavailable_reason = model_unavailable_reason(model_row)
    if unavailable_reason:
        return {"run_id": run_id, "model": None, "emotion": [], "unavailable_reason": unavailable_reason}

    assert model_row is not None
    agg_rows = paragraph_repo.fetch_topic_emotion_aggregates(run_id)
    if not agg_rows:
        return {
            "run_id": run_id,
            "model": model_meta(model_row),
            "emotion": [],
            "unavailable_reason": "no_emotion_rows: 无带 net_density 的段落曲线行",
        }

    by_topic = {int(row.topic_id): (float(row.emotion_total), float(row.weighted_token_total)) for row in agg_rows}
    emotion: list[dict[str, Any]] = []
    for topic_id in range(model_row.num_topics):
        entry = by_topic.get(topic_id)
        if entry is None or entry[1] <= 0:
            emotion.append({"topic_id": topic_id, "emotion": None, "weighted_token_total": None})
            continue
        emotion.append(
            {
                "topic_id": topic_id,
                "emotion": round(entry[0] / entry[1], 6),
                "weighted_token_total": round(entry[1], 4),
            }
        )
    return {"run_id": run_id, "model": model_meta(model_row), "emotion": emotion, "unavailable_reason": None}


def normalize_topic_weights(
    rows: Any,
    *,
    book_total: float,
    topic_words_map: dict[int, list[str]],
    topic_labels_map: dict[int, str],
) -> list[dict[str, Any]]:
    """主题权重只使用实际段落推断 token 总量归一化（无主题词的条目丢弃）"""
    result: list[dict[str, Any]] = []
    for row in rows:
        topic_id, weighted_total = validate_topic_aggregation_row(row)
        words = topic_words_map.get(topic_id, [])
        if not words:
            continue
        result.append(
            {
                "topic_id": topic_id,
                "words": words,
                "weight": round(weighted_total / book_total, 6),
                "label": topic_labels_map.get(topic_id),
            }
        )
    return result
