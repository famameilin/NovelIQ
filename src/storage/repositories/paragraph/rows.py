"""
段落仓储行模型 dataclass

ParagraphCurveRow/ParagraphMetricRow 供段落曲线与段落指标批量写入使用。
ParagraphMetricRow 只含仍落列的字段：函数词/语义分类计数分别写
paragraph_metrics 的 fw_*/semantic_* 明确列，surface_tension_z 写
paragraph_features 的 tension_z 行。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParagraphCurveRow:
    """批量写入段落曲线（密度 + 平滑值）"""

    paragraph_id: int
    pos_density: float | None
    neg_density: float | None
    net_density: float | None
    smoothed_net_density: float | None
    surface_tension: float | None
    smoothed_surface_tension: float | None


@dataclass(frozen=True)
class ParagraphMetricRow:
    """批量写入段落原始计数与充分统计量

    char_count / function_word_counts / semantic_category_counts /
    surface_tension_z / surface_tension 不进入本行；token_count 是本表分母口径。
    """

    paragraph_id: int
    token_count: int
    sentence_count: int
    sentence_char_sum: float
    sentence_char_sum_sq: float
    positive_weight_sum: float
    negative_weight_sum: float
    fight_weight_sum: float
    exclaim_count: int
    question_count: int
    pause_count: int
    dialogue_char_count: int
    sensory_hit_count: int
    imagery_hit_count: int
    metaphor_sentence_count: int
    # 身体反应转喻命中（独立计数，不进正负极性）
    body_reaction_hit_count: int
