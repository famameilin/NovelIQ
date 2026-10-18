"段落仓储行模型 dataclass"

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParagraphCurveRow:
    "用于批量写入段落曲线（密度 + 平滑值）"

    paragraph_id: int
    pos_density: float | None
    neg_density: float | None
    net_density: float | None
    smoothed_net_density: float | None
    surface_tension: float | None
    smoothed_surface_tension: float | None


@dataclass(frozen=True)
class ParagraphMetricRow:
    "用于批量写入段落原始计数与充分统计量"

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

    body_reaction_hit_count: int
