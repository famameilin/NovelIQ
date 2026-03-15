from __future__ import annotations

import statistics
from collections import Counter
from typing import Dict, List, Optional, Tuple


def compute_emotion_recovery_speed(
    emotion_values: List[float],
    threshold: float | None = None,
) -> Optional[float]:
    """
    计算情感恢复速度。

    2026-03-11 创建 - 初始版本
    2026-03-11 修改 - Claude - 修复 recovery_speed 阈值问题
        原因：固定阈值 emotion_recovery_threshold: 0.3 远大于情感值量级 (~0.01)，
        导致没有负向块被识别，recovery_speed 返回 None。
        修改：使用动态阈值，基于数据标准差计算，确保阈值适配实际数据量级。
    """
    if not emotion_values:
        return None

    if threshold is None:
        if len(emotion_values) > 1:
            std_dev = statistics.stdev(emotion_values)
            threshold = max(std_dev * 0.5, 0.005)
        else:
            threshold = 0.005

    baseline = sum(emotion_values) / len(emotion_values)

    recovery_distances = []
    for i, val in enumerate(emotion_values):
        if val < baseline - threshold:
            for j in range(i + 1, len(emotion_values)):
                if emotion_values[j] >= baseline - threshold * 0.5:
                    recovery_distances.append(j - i)
                    break

    if not recovery_distances:
        return None

    return sum(recovery_distances) / len(recovery_distances)


def compute_emotion_polarity_distribution(
    emotional_valences: List[str],
) -> Dict[str, float]:
    """
    计算情感极性分布。

    2026-03-13 修改 - TraeAI
    任务: chunk-annotation-schema-refactor
    修改内容: 支持五档枚举 (strong_positive/mild_positive/neutral/mild_negative/strong_negative)
    """
    if not emotional_valences:
        return {"positive_ratio": 0.0, "negative_ratio": 0.0, "neutral_ratio": 0.0}

    counts = Counter(emotional_valences)
    total = len(emotional_valences)

    positive_count = counts.get("strong_positive", 0) + counts.get("mild_positive", 0)
    negative_count = counts.get("strong_negative", 0) + counts.get("mild_negative", 0)
    neutral_count = counts.get("neutral", 0)

    return {
        "positive_ratio": positive_count / total,
        "negative_ratio": negative_count / total,
        "neutral_ratio": neutral_count / total,
    }


def compute_pivot_moment_density(
    pivot_moments: List[int],
) -> float:
    if not pivot_moments:
        return 0.0

    return sum(pivot_moments) / len(pivot_moments)


def compute_emotion_curve_type(
    emotion_values: List[float],
) -> str:
    """
    计算情感曲线类型，返回规范的六种原型分类。

    六种原型：
    - "白手起家": 情感从低谷逐渐上升 (前 < 中 < 后)
    - "伊卡洛斯": 情感先升后降 (前 < 中 > 后)
    - "落坑爬出": 情感先降后升 (前 > 中 < 后)
    - "持续下降": 情感持续走低 (前 > 中 > 后)
    - "灰姑娘": 情感先降后升再降 (前 > 中 < 后，且后半段继续下降)
    - "俄狄浦斯": 情感先升后降再升 (前 < 中 > 后，且后半段继续上升)

    修改历史：
    - 2026-03-11 创建 - Claude - 初始版本使用斜率判断
    - 2026-03-11 修改 - Claude - 修复非规范值问题，改用三段式趋势判断，
      原返回值"平稳型"/"起伏型"/"悲剧型"/"白手起家型"不符合云端诊断规范
    """
    if len(emotion_values) < 3:
        return "白手起家"

    n = len(emotion_values)
    third = n // 3

    first_segment = emotion_values[:third]
    mid_segment = emotion_values[third : 2 * third]
    last_segment = emotion_values[2 * third :]

    first_avg = sum(first_segment) / len(first_segment) if first_segment else 0.0
    mid_avg = sum(mid_segment) / len(mid_segment) if mid_segment else 0.0
    last_avg = sum(last_segment) / len(last_segment) if last_segment else 0.0

    if first_avg < mid_avg < last_avg:
        return "白手起家"
    elif first_avg > mid_avg > last_avg:
        return "持续下降"
    elif first_avg > mid_avg and mid_avg < last_avg:
        if len(last_segment) >= 2:
            last_quarter = emotion_values[3 * n // 4 :]
            last_quarter_avg = sum(last_quarter) / len(last_quarter) if last_quarter else last_avg
            if last_quarter_avg < last_avg:
                return "灰姑娘"
        return "落坑爬出"
    elif first_avg < mid_avg and mid_avg > last_avg:
        if len(last_segment) >= 2:
            last_quarter = emotion_values[3 * n // 4 :]
            last_quarter_avg = sum(last_quarter) / len(last_quarter) if last_quarter else last_avg
            if last_quarter_avg > last_avg:
                return "俄狄浦斯"
        return "伊卡洛斯"
    else:
        if first_avg < last_avg:
            return "白手起家"
        else:
            return "持续下降"


def compute_arc_delta(
    character_emotion_scores: List[Tuple[str, List[float]]],
) -> float:
    if not character_emotion_scores:
        return 0.0

    stds = []
    for name, scores in character_emotion_scores:
        if len(scores) >= 2:
            stds.append(statistics.stdev(scores))

    return sum(stds) / len(stds) if stds else 0.0


def compute_pos_neg_ratio(
    pos_densities: List[float],
    neg_densities: List[float],
) -> float:
    if not pos_densities and not neg_densities:
        return 0.0

    pos_sum = sum(pos_densities) if pos_densities else 0.0
    neg_sum = sum(neg_densities) if neg_densities else 0.0

    return pos_sum / (neg_sum + 1e-6)
