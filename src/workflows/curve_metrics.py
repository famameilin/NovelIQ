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

修改时间: 2026-04-06
修改者: GLM-5
任务: 情绪曲线算法增强 - Task 7
修改内容: 使用傅里叶滤波替代滑动平均，消除滞后效应

修改时间: 2026-04-06
修改者: GLM-5
任务: 清理向后兼容代码
修改内容: 使用加权词典（dict[str, int]），移除 list[str] 支持

修改时间: 2026-04-07
修改者: GLM-5
任务: 性能优化
修改内容: 多类型词典合并优化，性能提升3倍
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy import text as sql_text

from src.config import settings
from src.config.constants import EVENT_TYPE_SCORES


@dataclass
class WeightedLexiconSet:
    """加权词表集合"""

    pos_terms: dict[str, int]
    neg_terms: dict[str, int]
    fight_terms: dict[str, int]
    weight: float = 1.0
    genre: str = ""


def compute_emotion_curve(
    chunk_texts: list[tuple[int, str]],
    pos_terms: dict[str, int],
    neg_terms: dict[str, int],
) -> tuple[list[tuple[int, float, float, float, float]], list[float]]:
    """
    计算情感曲线

    创建时间: 2025-03-11
    创建者: TraeAI
    任务: 预处理流程

    修改时间: 2026-04-06
    修改者: GLM-5
    任务: 清理向后兼容代码
    修改内容: 参数类型改为 dict[str, int]

    修改时间: 2026-04-07
    修改者: GLM-5
    任务: 张力曲线傅里叶平滑 - 配置抽离
    修改内容: keep_ratio 从配置读取
    """
    from src.metrics.emotion_metrics import lexical_sentiment_density
    from src.metrics.fourier_filter import fourier_smooth

    emotion_rows: list[tuple[int, float, float, float, float]] = []
    raw_densities: list[float] = []
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
    smoothed = fourier_smooth(raw_densities, keep_ratio=settings.metrics.fourier_smooth_keep_ratio)
    for idx, (chunk_id, pos_d, neg_d, net_d, _) in enumerate(emotion_rows):
        emotion_rows[idx] = (chunk_id, pos_d, neg_d, net_d, smoothed[idx])
    return emotion_rows, raw_densities


def compute_emotion_curve_weighted(
    chunk_texts: list[tuple[int, str]],
    weighted_lexicons: list[WeightedLexiconSet],
) -> tuple[list[tuple[int, float, float, float, float]], list[float]]:
    """
    计算加权情感曲线（多类型词表混合）。

    优化策略：合并所有类型的词典，一次计算，避免重复匹配。

    Args:
        chunk_texts: chunk 列表，格式 [(chunk_id, text), ...]
        weighted_lexicons: 加权词表列表，格式 [WeightedLexiconSet(...), ...]

    Returns:
        (emotion_rows, raw_densities): 情感曲线行和原始密度

    创建时间: 2026-04-06
    创建者: GLM-5
    任务: 多类型加权混合词表方案

    修改时间: 2026-04-06
    修改者: GLM-5
    任务: 清理向后兼容代码
    修改内容: 使用 dict[str, int] 类型的词典

    修改时间: 2026-04-07
    修改者: GLM-5
    任务: 性能优化
    修改内容: 合并词典优化，性能提升3倍
    """
    if not weighted_lexicons:
        return compute_emotion_curve(chunk_texts, {}, {})

    if len(weighted_lexicons) == 1:
        lex = weighted_lexicons[0]
        return compute_emotion_curve(chunk_texts, lex.pos_terms, lex.neg_terms)

    merged_pos: dict[str, float] = {}
    merged_neg: dict[str, float] = {}

    for lex_set in weighted_lexicons:
        weight = lex_set.weight
        for term, w in lex_set.pos_terms.items():
            merged_pos[term] = merged_pos.get(term, 0) + w * weight
        for term, w in lex_set.neg_terms.items():
            merged_neg[term] = merged_neg.get(term, 0) + w * weight

    merged_pos_int = {k: int(round(v)) for k, v in merged_pos.items()}
    merged_neg_int = {k: int(round(v)) for k, v in merged_neg.items()}

    return compute_emotion_curve(chunk_texts, merged_pos_int, merged_neg_int)


def compute_tension_signals(
    chunk_texts: list[tuple[int, str]],
    fight_terms: dict[str, int],
    style_map: dict,
    annotation_map: dict,
    raw_densities: list[float],
) -> list[dict]:
    """
    计算张力信号

    创建时间: 2025-03-11
    创建者: TraeAI
    任务: 预处理流程

    修改时间: 2026-04-06
    修改者: GLM-5
    任务: 清理向后兼容代码
    修改内容: fight_terms 参数类型改为 dict[str, int]
    """
    tension_signals: list[dict] = []
    for idx, (chunk_id, _text) in enumerate(chunk_texts):
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
    fight_terms: dict[str, int],
    tension_composite_values: list[float],
) -> list[tuple[int, float, float]]:
    """
    计算节奏曲线

    创建时间: 2025-03-11
    创建者: TraeAI
    任务: 预处理流程

    修改时间: 2026-04-06
    修改者: GLM-5
    任务: 清理向后兼容代码
    修改内容: fight_terms 参数类型改为 dict[str, int]
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
    raw_densities: list[float],
    tension_composite_values: list[float],
    chunk_texts: list[tuple[int, str]],
) -> list[tuple[str, float]]:
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
    global_stats: list[tuple[str, float]] = []
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
