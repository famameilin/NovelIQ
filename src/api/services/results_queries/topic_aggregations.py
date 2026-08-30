"""主题聚合查询服务（《分析能力扩展路线图》§5.11 / D1-D3）。

全部复合结果查询时计算，不落结果表；每个聚合携带模型契约元数据与
样本量，缺失或样本不足时返回 unavailable_reason，不用零值伪造结果。
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from src.config import settings
from src.storage.repositories import ParagraphRepository


def _model_meta(dict_row: Any | None) -> dict[str, Any] | None:
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


def _model_unavailable_reason(model_row: Any | None) -> str | None:
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
    unavailable_reason = _model_unavailable_reason(model_row)
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
        "model": _model_meta(model_row),
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
    unavailable_reason = _model_unavailable_reason(model_row)
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
    token_by_chapter = {int(row.chapter_id): int(row.token_total) for row in token_rows}

    chapters: dict[int, dict[str, Any]] = {}
    for row in agg_rows:
        chapter_id = int(row.chapter_id)
        entry = chapters.setdefault(
            chapter_id,
            {"chapter_id": chapter_id, "chapter_sequence": int(row.sequence), "chapter_title": row.title},
        )
        entry.setdefault("distribution", {})[int(row.topic_id)] = float(row.weighted_total)

    num_topics = model_row.num_topics
    result: list[dict[str, Any]] = []
    for chapter_id in sorted(chapters, key=lambda cid: chapters[cid]["chapter_sequence"]):
        entry = chapters[chapter_id]
        token_total = token_by_chapter.get(chapter_id, 0)
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
        "model": _model_meta(model_row),
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
    unavailable_reason = _model_unavailable_reason(model_row)
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
        "model": _model_meta(model_row),
        "num_topics": num_topics,
        "points": ordered,
        "unavailable_reason": None,
    }


def _kl_divergence_log2(p: np.ndarray, q: np.ndarray) -> float:
    """p log2(p/q)，p == 0 处贡献为 0；q 在 p > 0 处恒正（由 m 构造保证）"""
    mask = p > 0
    return float(np.sum(p[mask] * np.log2(p[mask] / q[mask])))


def jensen_shannon_divergence(p: list[float] | np.ndarray, q: list[float] | np.ndarray) -> float:
    """
    以 2 为底、范围 [0, 1] 的 JS 散度（§5.11 D2 的 topic_shift_score 定义）

    若调用 SciPy jensenshannon 返回的是距离，需平方一次才是散度；
    本实现直接按散度定义计算，避免依赖与二次方修正。
    """
    p_arr = np.asarray(p, dtype=np.float64)
    q_arr = np.asarray(q, dtype=np.float64)
    if p_arr.shape != q_arr.shape or p_arr.size == 0:
        raise ValueError("JS 散度需要同维、非空的概率向量")
    midpoint = 0.5 * (p_arr + q_arr)
    return 0.5 * (_kl_divergence_log2(p_arr, midpoint) + _kl_divergence_log2(q_arr, midpoint))


def compute_topic_shift_candidates(
    series: dict[str, Any],
    *,
    window_size: int | None = None,
    min_tokens_per_window: int | None = None,
    score_threshold: float | None = None,
    max_candidates: int | None = None,
) -> dict[str, Any]:
    """
    主题变化候选点（D2）：相邻不重叠窗口的归一化主题分布 JS 散度

    窗口分布 = 窗口内段落权重的入模 token 加权平均；窗口实际入模 token
    总数低于 min_tokens_per_window 时跳过，避免极短段落制造高噪声尖峰。
    候选点位置取前窗口最后一段的字符结束位置。
    """
    shift_settings = settings.topic_model.topic_shift
    window_size = window_size if window_size is not None else shift_settings.window_size
    min_tokens = min_tokens_per_window if min_tokens_per_window is not None else shift_settings.min_tokens_per_window
    threshold = score_threshold if score_threshold is not None else shift_settings.score_threshold
    max_candidates = max_candidates if max_candidates is not None else shift_settings.max_candidates

    points = series.get("points") or []
    if len(points) < 2:
        return {
            "unavailable_reason": "insufficient_windows: 段落样本不足，无法构成至少两个窗口",
            "candidates": [],
            "config": _shift_config(window_size, min_tokens, threshold, max_candidates),
        }

    window_aggs: list[tuple[int, int, np.ndarray, float]] = []
    i = 0
    n = len(points)
    while i < n:
        end = min(i + window_size, n)
        tokens = np.array([float(p["token_count"]) for p in points[i:end]], dtype=np.float64)
        token_total = float(tokens.sum())
        if token_total >= min_tokens:
            weights = np.array([p["weights"] for p in points[i:end]], dtype=np.float64)
            weighted_sum = np.sum(weights * tokens[:, None], axis=0)
            window_dist = weighted_sum / token_total
            window_aggs.append((i, end - 1, window_dist, token_total))
        i = end

    candidates: list[dict[str, Any]] = []
    for left, right in zip(window_aggs, window_aggs[1:], strict=False):
        if len(candidates) >= max_candidates:
            break
        score = jensen_shannon_divergence(left[2], right[2])
        if score < threshold:
            continue
        candidates.append(
            {
                "position": int(points[right[0]]["start_position"]),
                "paragraph_start": points[left[0]]["paragraph_id"],
                "paragraph_end": points[left[1]]["paragraph_id"],
                "score": round(float(score), 6),
                "window_token_total": int(left[3]),
            }
        )

    return {
        "unavailable_reason": None if candidates else "no_candidates: 相邻窗口未达到阈值",
        "candidates": candidates,
        "config": _shift_config(window_size, min_tokens, threshold, max_candidates),
    }


def _shift_config(window_size: int, min_tokens: int, threshold: float, max_candidates: int) -> dict[str, Any]:
    return {
        "window_size": window_size,
        "min_tokens_per_window": min_tokens,
        "score_threshold": threshold,
        "max_candidates": max_candidates,
    }


def compute_topic_emotion(run_id: str, session: Session) -> dict[str, Any]:
    """
    主题-情感统计（D3）：sum(weight * token * net_density) / sum(weight * token)

    情感输入使用 paragraph_curves.net_density 原始值；空值段落在 SQL 层
    同时从分子分母排除；权重和为零时返回空值并记录原因。
    """
    paragraph_repo = ParagraphRepository(session)
    model_row = paragraph_repo.fetch_topic_model_run(run_id)
    unavailable_reason = _model_unavailable_reason(model_row)
    if unavailable_reason:
        return {"run_id": run_id, "model": None, "emotion": [], "unavailable_reason": unavailable_reason}

    assert model_row is not None
    agg_rows = paragraph_repo.fetch_topic_emotion_aggregates(run_id)
    if not agg_rows:
        return {
            "run_id": run_id,
            "model": _model_meta(model_row),
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
    return {"run_id": run_id, "model": _model_meta(model_row), "emotion": emotion, "unavailable_reason": None}