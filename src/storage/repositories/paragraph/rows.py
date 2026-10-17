"""
段落仓储行模型 dataclass

创建时间: 2026-10-02
创建者: Trae
任务: 大文件拆分——从 paragraph_repository.py 提取行模型（约 37-76 行）
说明: 纯结构搬移，不改字段与行为；ParagraphCurveRow/ParagraphMetricRow
供段落曲线与段落指标批量写入使用。paragraph_repository 模块保留
re-export，导入方零改动。

2026-10-16 全库 3NF 改造：ParagraphMetricRow 只保留仍然落列的字段——
char_count 是段落正文长度的读取投影，function_word_counts /
semantic_category_counts 写 paragraph_metrics 的 20 个 fw_* / 10 个
semantic_* 明确列，surface_tension_z 写 paragraph_features 的 tension_z 行
（sigmoid 展示值读取投影），均不再随本行写入。
ParagraphCurveRow 保留（曲线面负责其字段语义）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParagraphCurveRow:
    """2026-08-14 用于批量写入段落曲线（密度 + 平滑值）"""

    paragraph_id: int
    pos_density: float | None
    neg_density: float | None
    net_density: float | None
    smoothed_net_density: float | None
    surface_tension: float | None
    smoothed_surface_tension: float | None


@dataclass(frozen=True)
class ParagraphMetricRow:
    """2026-08-14 用于批量写入段落原始计数与充分统计量

    2026-10-16 3NF：char_count / function_word_counts /
    semantic_category_counts / surface_tension_z / surface_tension 不再是
    paragraph_metrics 的可写列，故不进入本行；token_count 仍是本表分母口径。
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
    # 2026-09-05 C 批：身体反应转喻命中（独立计数，不进正负极性）
    body_reaction_hit_count: int
