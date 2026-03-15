"""
曲线/统计相关的度量计算（从 preprocess 中拆出）

创建时间: 2026-03-14
创建者: TraeAI
任务: workflows 内部拆分
说明: 聚合与预处理都会用到的通用计算放在这里，减少模块间交叉依赖。

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration
修改内容: 使用 SQLAlchemy text() 包装 SQL 语句
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import List, Tuple

from loguru import logger
from sqlalchemy import text as sql_text

from src.lexicons.loader import load_lexicon


EVENT_TYPE_SCORES = {
    "高潮": 1.0,
    "冲突": 0.8,
    "转折": 0.6,
    "铺垫": 0.4,
    "日常": 0.2,
}


def load_all_lexicons(lexicon_dir: Path) -> dict:
    """
    加载情感词典

    创建时间: 2025-03-11
    创建者: TraeAI
    任务: 预处理流程
    """
    lexicons = {}
    for lexicon_name in ["positive", "negative", "combat"]:
        try:
            lexicons[lexicon_name] = load_lexicon(lexicon_name, lexicon_dir)
        except FileNotFoundError:
            lexicons[lexicon_name] = []
            logger.warning(f"{lexicon_name} lexicon not found")
    return lexicons


def compute_emotion_curve(
    chunk_texts: List[Tuple[int, str]],
    pos_terms: List[str],
    neg_terms: List[str],
) -> Tuple[List[Tuple[int, float, float, float, float]], List[float]]:
    """
    计算情感曲线

    创建时间: 2025-03-11
    创建者: TraeAI
    任务: 预处理流程
    """
    from src.metrics.emotion_metrics import lexical_sentiment_density, moving_average

    emotion_rows: List[Tuple[int, float, float, float, float]] = []
    raw_densities: List[float] = []
    for chunk_id, text in chunk_texts:
        result = lexical_sentiment_density(text, pos_terms, neg_terms)
        emotion_rows.append(
            (
                chunk_id,
                result["pos_density"],
                result["neg_density"],
                result["net_density"],
                0.0,
            )
        )
        raw_densities.append(result["net_density"])
    smoothed = moving_average(raw_densities, window=5)
    for idx, (chunk_id, pos_d, neg_d, net_d, _) in enumerate(emotion_rows):
        emotion_rows[idx] = (chunk_id, pos_d, neg_d, net_d, smoothed[idx])
    return emotion_rows, raw_densities


def compute_tension_signals(
    chunk_texts: List[Tuple[int, str]],
    fight_terms: List[str],
    style_map: dict,
    annotation_map: dict,
    raw_densities: List[float],
) -> List[dict]:
    """
    计算张力信号

    创建时间: 2025-03-11
    创建者: TraeAI
    任务: 预处理流程
    """
    tension_signals: List[dict] = []
    for chunk_id, text in chunk_texts:
        dialogue_val = 0.0
        sent_len_std = 0.0
        if chunk_id in style_map:
            dialogue_val = style_map[chunk_id][0]
            sent_len_std = style_map[chunk_id][1]
        event_type = ""
        cliffhanger = 0
        if chunk_id in annotation_map:
            event_type = annotation_map[chunk_id][0] or ""
            cliffhanger = annotation_map[chunk_id][1]
        event_score = EVENT_TYPE_SCORES.get(event_type, 0.0)
        cliffhanger_score = 1.0 if cliffhanger else 0.0
        emotion_intensity = abs(raw_densities[chunk_id] if chunk_id < len(raw_densities) else 0.0)
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
    chunk_texts: List[Tuple[int, str]],
    fight_terms: List[str],
    tension_composite_values: List[float],
) -> List[Tuple[int, float, float]]:
    """
    计算节奏曲线

    创建时间: 2025-03-11
    创建者: TraeAI
    任务: 预处理流程
    """
    from src.metrics.rhythm_metrics import tension_proxy

    rhythm_rows: List[Tuple[int, float, float]] = []
    for idx, (chunk_id, text) in enumerate(chunk_texts):
        proxy = tension_proxy(text, fight_terms)
        proxy_score = sum(proxy.values()) / len(proxy) if proxy else 0.0
        rhythm_rows.append((chunk_id, proxy_score, tension_composite_values[idx]))
    return rhythm_rows


def compute_global_stats(
    conn,
    raw_densities: List[float],
    tension_composite_values: List[float],
    chunk_texts: List[Tuple[int, str]],
) -> List[Tuple[str, float]]:
    """
    计算全局统计

    创建时间: 2025-03-11
    创建者: TraeAI
    任务: 预处理流程

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: postgresql-migration
    修改内容: 使用 SQLAlchemy text() 包装 SQL 语句
    """
    global_stats: List[Tuple[str, float]] = []
    style_rows = conn.execute(sql_text("SELECT mtld, ttr, avg_sent_len FROM chunk_style")).fetchall()
    if style_rows:
        mtld_vals = [r[0] for r in style_rows if r[0] is not None]
        ttr_vals = [r[1] for r in style_rows if r[1] is not None]
        sent_len_vals = [r[2] for r in style_rows if r[2] is not None]
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
        global_stats.append(("emotion_max_chunk", float(chunk_texts[max_idx][0])))
        global_stats.append(("emotion_min_chunk", float(chunk_texts[min_idx][0])))
    if tension_composite_values:
        global_stats.append(("rhythm_avg", sum(tension_composite_values) / len(tension_composite_values)))
        variance = sum(
            (v - sum(tension_composite_values) / len(tension_composite_values)) ** 2 for v in tension_composite_values
        ) / len(tension_composite_values)
        global_stats.append(("rhythm_std", math.sqrt(variance)))
        global_stats.append(("rhythm_max", max(tension_composite_values)))
        global_stats.append(("rhythm_min", min(tension_composite_values)))
    return global_stats
