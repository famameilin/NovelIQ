"""
曲线/统计相关的度量计算（从 preprocess 中拆出）

聚合与预处理都会用到的通用计算放在这里，减少模块间交叉依赖




"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import text as sql_text

from src.config import settings
from src.config.constants import EVENT_TYPE_SCORES


@dataclass
class WeightedLexiconSet:
    """加权词表集合"""

    pos_terms: Mapping[str, float]
    neg_terms: Mapping[str, float]
    fight_terms: Mapping[str, float]
    weight: float = 1.0
    genre: str = ""


def _compute_emotion_curve_raw(
    chunk_texts: list[tuple[int, str]],
    pos_terms: Mapping[str, float],
    neg_terms: Mapping[str, float],
) -> tuple[list[tuple[int, float, float, float]], list[float]]:
    """
    计算未平滑的情感密度序列

    """
    from src.metrics.emotion_metrics import lexical_sentiment_density

    emotion_rows: list[tuple[int, float, float, float]] = []
    raw_densities: list[float] = []
    for chunk_id, text in chunk_texts:
        result = lexical_sentiment_density(text, pos_terms, neg_terms)
        emotion_rows.append(
            (
                chunk_id,
                result["pos_density"],
                result["neg_density"],
                result["net_density"],
            )
        )
        raw_densities.append(result["net_density"])
    return emotion_rows, raw_densities


def compute_emotion_curve(
    chunk_texts: list[tuple[int, str]],
    pos_terms: Mapping[str, float],
    neg_terms: Mapping[str, float],
) -> tuple[list[tuple[int, float, float, float, float]], list[float]]:
    """
    计算情感曲线




    """
    from src.metrics.fourier_filter import fourier_smooth

    raw_rows, raw_densities = _compute_emotion_curve_raw(chunk_texts, pos_terms, neg_terms)
    emotion_rows = [(chunk_id, pos_d, neg_d, net_d, 0.0) for chunk_id, pos_d, neg_d, net_d in raw_rows]
    smoothed = fourier_smooth(raw_densities, keep_ratio=settings.metrics.fourier_smooth_keep_ratio)
    for idx, (chunk_id, pos_d, neg_d, net_d, _) in enumerate(emotion_rows):
        emotion_rows[idx] = (chunk_id, pos_d, neg_d, net_d, smoothed[idx])
    return emotion_rows, raw_densities


def compute_emotion_curve_weighted(
    chunk_texts: list[tuple[int, str]],
    weighted_lexicons: list[WeightedLexiconSet],
) -> tuple[list[tuple[int, float, float, float, float]], list[float]]:
    """
    计算加权情感曲线（多类型词表混合）

    优化策略：合并所有类型的词典，一次计算，避免重复匹配

    Args:
        chunk_texts: chunk 列表，格式 [(chunk_id, text), ...]
        weighted_lexicons: 加权词表列表，格式 [WeightedLexiconSet(...), ...]

    Returns:
        (emotion_rows, raw_densities): 情感曲线行和原始密度




    """
    from src.metrics.fourier_filter import fourier_smooth

    if not weighted_lexicons:
        return compute_emotion_curve(chunk_texts, {}, {})

    active_lexicons = [lex for lex in weighted_lexicons if lex.weight > 0]
    if not active_lexicons:
        return compute_emotion_curve(chunk_texts, {}, {})

    if len(active_lexicons) == 1:
        lex = active_lexicons[0]
        return compute_emotion_curve(chunk_texts, lex.pos_terms, lex.neg_terms)

    per_genre_rows: list[tuple[float, list[tuple[int, float, float, float]]]] = []
    for lex_set in active_lexicons:
        raw_rows, _ = _compute_emotion_curve_raw(chunk_texts, lex_set.pos_terms, lex_set.neg_terms)
        per_genre_rows.append((lex_set.weight, raw_rows))

    combined_rows: list[tuple[int, float, float, float, float]] = []
    raw_densities: list[float] = []

    # 这里必须先按 genre 各自完成词表命中，再在 chunk 结果层做加权
    # 否则像 0.25 这类低权重词条在总词表阶段就会被压成 0，命中了也不再贡献任何情绪值
    for chunk_index, (chunk_id, _text) in enumerate(chunk_texts):
        pos_density = 0.0
        neg_density = 0.0
        net_density = 0.0
        for genre_weight, raw_rows in per_genre_rows:
            _row_chunk_id, pos_d, neg_d, net_d = raw_rows[chunk_index]
            pos_density += pos_d * genre_weight
            neg_density += neg_d * genre_weight
            net_density += net_d * genre_weight
        combined_rows.append((chunk_id, pos_density, neg_density, net_density, 0.0))
        raw_densities.append(net_density)

    smoothed = fourier_smooth(raw_densities, keep_ratio=settings.metrics.fourier_smooth_keep_ratio)
    for idx, (chunk_id, pos_d, neg_d, net_d, _) in enumerate(combined_rows):
        combined_rows[idx] = (chunk_id, pos_d, neg_d, net_d, smoothed[idx])

    return combined_rows, raw_densities


def compute_tension_signals(
    chunk_texts: list[tuple[int, str]],
    fight_terms: dict[str, float],
    style_map: dict[int, dict[str, float | None]],
    annotation_map: dict[int, dict[str, str | int | None]],
    raw_densities: list[float],
) -> list[dict]:
    """
    计算张力信号



    """
    tension_signals: list[dict] = []
    for idx, (chunk_id, _text) in enumerate(chunk_texts):
        dialogue_val = 0.0
        sent_len_std = 0.0
        style_info = style_map.get(chunk_id)
        if style_info:
            dialogue_val = float(style_info.get("dialogue_ratio") or 0.0)
            sent_len_std = float(style_info.get("sent_len_std") or 0.0)
        event_type = ""
        cliffhanger = 0
        annotation_info = annotation_map.get(chunk_id)
        if annotation_info:
            event_type = str(annotation_info.get("event_type") or "")
            cliffhanger = int(annotation_info.get("cliffhanger") or 0)
        event_score = EVENT_TYPE_SCORES.get(event_type, 0.0)
        cliffhanger_score = 1.0 if cliffhanger else 0.0
        emotion_intensity = abs(raw_densities[idx] if idx < len(raw_densities) else 0.0)
        tension_signals.append(
            {
                "emotion_intensity": emotion_intensity,
                "dialogue_ratio": dialogue_val,
                "sent_len_std": sent_len_std,
                "event_score": event_score,
                "cliffhanger_score": cliffhanger_score,
            }
        )
    return tension_signals


def compute_rhythm_curve(
    chunk_texts: list[tuple[int, str]],
    fight_terms: dict[str, float],
    tension_composite_values: list[float],
) -> list[tuple[int, float, float]]:
    """
    计算节奏曲线


    """
    from src.metrics.rhythm_metrics import tension_proxy

    rhythm_rows: list[tuple[int, float, float]] = []
    for idx, (chunk_id, text) in enumerate(chunk_texts):
        proxy = tension_proxy(text, fight_terms)
        proxy_score = sum(proxy.values()) / len(proxy) if proxy else 0.0
        rhythm_rows.append((chunk_id, proxy_score, tension_composite_values[idx]))
    return rhythm_rows


def compute_global_stats(
    conn,
    run_id: str,
    raw_densities: list[float],
    tension_composite_values: list[float],
    chunk_texts: list[tuple[int, str]],
) -> list[tuple[str, float]]:
    """
    计算全局统计


    """
    global_stats: list[tuple[str, float]] = []
    # 2026-08-13 修复：chunk_style 是跨 run 累积的表，此前缺 run_id 过滤，
    # 多 run 后 global_avg_* 被其他 run 的行污染
    style_rows = conn.execute(
        sql_text("SELECT mtld, ttr, avg_sent_len FROM chunk_style WHERE run_id = :run_id"),
        {"run_id": run_id},
    ).fetchall()
    if style_rows:
        mtld_vals = [row.mtld for row in style_rows if row.mtld is not None]
        ttr_vals = [row.ttr for row in style_rows if row.ttr is not None]
        sent_len_vals = [row.avg_sent_len for row in style_rows if row.avg_sent_len is not None]
        if mtld_vals:
            global_stats.append(("global_avg_mtld", sum(mtld_vals) / len(mtld_vals)))
        if ttr_vals:
            global_stats.append(("global_avg_ttr", sum(ttr_vals) / len(ttr_vals)))
        if sent_len_vals:
            global_stats.append(("global_avg_sent_len", sum(sent_len_vals) / len(sent_len_vals)))
    if raw_densities:
        global_stats.append(("emotion_avg", sum(raw_densities) / len(raw_densities)))
        variance = sum((d - sum(raw_densities) / len(raw_densities)) ** 2 for d in raw_densities) / len(raw_densities)
        global_stats.append(("emotion_std", math.sqrt(variance)))
        global_stats.append(("emotion_max", max(raw_densities)))
        global_stats.append(("emotion_min", min(raw_densities)))
        max_idx = raw_densities.index(max(raw_densities))
        min_idx = raw_densities.index(min(raw_densities))
        max_chunk_id, _max_text = chunk_texts[max_idx]
        min_chunk_id, _min_text = chunk_texts[min_idx]
        global_stats.append(("emotion_max_chunk", float(max_chunk_id)))
        global_stats.append(("emotion_min_chunk", float(min_chunk_id)))
    if tension_composite_values:
        global_stats.append(("rhythm_avg", sum(tension_composite_values) / len(tension_composite_values)))
        variance = sum(
            (v - sum(tension_composite_values) / len(tension_composite_values)) ** 2 for v in tension_composite_values
        ) / len(tension_composite_values)
        global_stats.append(("rhythm_std", math.sqrt(variance)))
        global_stats.append(("rhythm_max", max(tension_composite_values)))
        global_stats.append(("rhythm_min", min(tension_composite_values)))
    return global_stats
