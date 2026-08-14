"""
段落表层张力（设计文档《章节粒度分析指标重设计》§9.2）

流程：分量原始值 → run 内稳健标准化（median / MAD，clip 到 [-3, 3]）
→ 等权/配置权重加权平均 z → sigmoid 映射到 (0, 1)。

初始分量（只表达可从文本表面观测的激活强度）：
    fight    战斗词加权命中率
    exclaim  感叹号每百字频率
    question 问号每百字频率
    dialogue 对话字符占比
    pause    停顿标点每百字频率
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from statistics import median

from src.config import settings
from src.metrics.paragraph_metrics import ParagraphMetricCounts

# 稳健标准化常量（§9.2）：z = clip((value - median) / (1.4826 * MAD + epsilon), -3, 3)
MAD_SCALE = 1.4826
MAD_EPSILON = 1e-9
Z_CLIP = 3.0

COMPONENT_KEYS = ("fight", "exclaim", "question", "dialogue", "pause")


def surface_tension_components(counts: ParagraphMetricCounts) -> dict[str, float]:
    """返回 5 个表层张力分量的原始值（未标准化，分母为零时按 1 保护）"""
    token_denominator = max(counts.token_count, 1)
    char_denominator = max(counts.char_count, 1)
    return {
        "fight": counts.fight_weight_sum / token_denominator,
        "exclaim": counts.exclaim_count / char_denominator * 100.0,
        "question": counts.question_count / char_denominator * 100.0,
        "dialogue": counts.dialogue_char_count / char_denominator,
        "pause": counts.pause_count / char_denominator * 100.0,
    }


def robust_standardize_components(
    component_lists: Sequence[dict[str, float]],
) -> list[dict[str, float]]:
    """
    run 内稳健标准化：对每个分量键收集全部段落的值，按
    z = clip((value - median) / (1.4826 * MAD + epsilon), -3, 3) 标准化

    输入为空返回空列表；全常量序列（MAD = 0）时所有 z 为 0。
    返回与输入等长的列表，键为全部输入键的并集（缺失值按 0 处理）。
    """
    if not component_lists:
        return []

    keys: list[str] = []
    for components in component_lists:
        for key in components:
            if key not in keys:
                keys.append(key)

    z_components: list[dict[str, float]] = [{} for _ in component_lists]

    for key in keys:
        values = [float(components.get(key, 0.0)) for components in component_lists]
        center = median(values)
        deviations = [abs(value - center) for value in values]
        denominator = MAD_SCALE * median(deviations) + MAD_EPSILON
        for index, value in enumerate(values):
            z = (value - center) / denominator
            z_components[index][key] = min(max(z, -Z_CLIP), Z_CLIP)

    return z_components


def surface_tension_z_value(
    z_components: dict[str, float],
    weights: dict[str, float] | None = None,
) -> float:
    """
    加权平均 z 值

    weights 默认 settings.metrics.surface_tension_weights（初始等权）；
    z_components 缺失的键按 0 处理；权重和为 0 时返回 0（防御）。
    """
    if weights is None:
        weights = settings.metrics.surface_tension_weights
    total = 0.0
    weight_sum = 0.0
    for key, weight in weights.items():
        weight_sum += weight
        total += z_components.get(key, 0.0) * weight
    if weight_sum == 0.0:
        return 0.0
    return total / weight_sum


def surface_tension_sigmoid(z: float) -> float:
    """sigmoid 映射：sigmoid(0) = 0.5，值域 (0, 1)"""
    return 1.0 / (1.0 + math.exp(-z))
