from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Sequence


def _validate_position_inputs(positions: Sequence[float], scores: Sequence[float]) -> None:
    """校验字符坐标版输入的公共前置条件：长度一致且位置严格单调递增。"""
    if len(positions) != len(scores):
        raise ValueError("positions 与 scores 长度必须一致")
    if len(positions) >= 2:
        for prev, curr in zip(positions[:-1], positions[1:], strict=True):
            if curr <= prev:
                raise ValueError("positions 必须严格单调递增")


def compute_emotion_recovery_speed(
    positions: Sequence[float],
    scores: Sequence[float],
) -> float | None:
    """情绪恢复速度：低谷到回升的归一化进度距离均值；无法识别时 null。"""
    if not scores:
        return None
    _validate_position_inputs(positions, scores)

    if len(scores) > 1:
        std_dev = statistics.stdev(scores)
        threshold = max(std_dev * 0.5, 0.005)
    else:
        threshold = 0.005

    baseline = sum(scores) / len(scores)
    recovery_distances = []
    for i, val in enumerate(scores):
        if val < baseline - threshold:
            for j in range(i + 1, len(scores)):
                if scores[j] >= baseline - threshold * 0.5:
                    recovery_distances.append(positions[j] - positions[i])
                    break

    if not recovery_distances:
        return None
    return sum(recovery_distances) / len(recovery_distances)



def compute_emotion_polarity_distribution(
    emotional_valences: list[str],
) -> dict[str, float | None]:
    """计算正向、负向和中性情绪的占比；无有效情绪标注时三项均为 None（契约 null 语义）"""
    if not emotional_valences:
        return {"positive_ratio": None, "negative_ratio": None, "neutral_ratio": None}

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
    pivot_moments: list[int],
) -> float:
    if not pivot_moments:
        return 0.0

    return sum(pivot_moments) / len(pivot_moments)



def compute_lexical_emotion_trend_detail(
    positions: Sequence[float],
    scores: Sequence[float],
) -> dict:
    """
    字符坐标版前中后情绪趋势（设计文档 §10、§19.8 修复）。

    与 compute_lexical_emotion_trend 的差异：
    - 前中后三等分按字符区间切分：前段 = positions 落在 [0, 1/3)，
      中段 = [1/3, 2/3)，后段 = [2/3, 1]（相对总字符跨度的位置）；
    - 每段统计为字符跨度加权均值：点的权重取该点覆盖的字符宽度
      （相邻位置差的一半，端点用边缘宽度），等间距时退化为等权均值；
    - 波动/趋势分类沿用旧口径：stdev >= 0.003 判 volatile，
      段均差 diff = last_avg - first_avg 超过 0.002 判 rising/falling。

    返回字段:
    - first_avg: 前段 [0, 1/3) 字符区间的加权均值
    - middle_avg: 中段 [1/3, 2/3) 字符区间的加权均值
    - last_avg: 后段 [2/3, 1] 字符区间的加权均值
    - stdev: 全段样本标准差（沿用波动判定阈值）
    - trend: rising / falling / stable / volatile
    """
    _validate_position_inputs(positions, scores)
    if len(scores) < 3:
        return {
            "first_avg": 0.0,
            "middle_avg": 0.0,
            "last_avg": 0.0,
            "stdev": 0.0,
            "trend": "stable",
        }

    total = len(scores)
    span = positions[-1] - positions[0]

    def segment_avg(indices: list[int]) -> float:
        if not indices:
            return 0.0
        if span <= 0:
            # 字符跨度为零：按点等权均值兜底。
            return sum(scores[j] for j in indices) / len(indices)
        weights = []
        for j in indices:
            if j == 0:
                weight = positions[1] - positions[0]
            elif j == total - 1:
                weight = positions[-1] - positions[-2]
            else:
                weight = (positions[j + 1] - positions[j - 1]) / 2
            weights.append(weight)
        weight_sum = sum(weights)
        if weight_sum <= 0:
            return 0.0
        return sum(scores[j] * weight for j, weight in zip(indices, weights, strict=True)) / weight_sum

    if span <= 0:
        # 字符跨度为零：按点索引三等分兜底（与旧函数行为一致）。
        third = total // 3
        first_indices = list(range(0, third))
        middle_indices = list(range(third, 2 * third))
        last_indices = list(range(2 * third, total))
    else:
        first_boundary = positions[0] + span / 3
        second_boundary = positions[0] + 2 * span / 3
        first_indices = [j for j in range(total) if positions[j] < first_boundary]
        middle_indices = [
            j for j in range(total) if first_boundary <= positions[j] < second_boundary
        ]
        last_indices = [j for j in range(total) if positions[j] >= second_boundary]

    first_avg = segment_avg(first_indices)
    middle_avg = segment_avg(middle_indices)
    last_avg = segment_avg(last_indices)

    stdev = statistics.stdev(scores) if len(scores) > 1 else 0.0
    diff = last_avg - first_avg

    if stdev >= 0.003:
        trend = "volatile"
    elif diff > 0.002:
        trend = "rising"
    elif diff < -0.002:
        trend = "falling"
    else:
        trend = "stable"

    return {
        "first_avg": round(first_avg, 6),
        "middle_avg": round(middle_avg, 6),
        "last_avg": round(last_avg, 6),
        "stdev": round(stdev, 6),
        "trend": trend,
    }


def compute_arc_delta(
    character_emotion_scores: list[tuple[str, list[float]]],
) -> float | None:
    if not character_emotion_scores:
        return None

    stds = []
    for _, scores in character_emotion_scores:
        if len(scores) >= 2:
            stds.append(statistics.stdev(scores))

    return sum(stds) / len(stds) if stds else None


def compute_pos_neg_ratio(
    pos_densities: list[float],
    neg_densities: list[float],
) -> float | None:
    if not pos_densities and not neg_densities:
        return None

    pos_sum = sum(pos_densities) if pos_densities else 0.0
    neg_sum = sum(neg_densities) if neg_densities else 0.0

    return pos_sum / (neg_sum + 1e-6)


def compute_lexical_emotion_trend(
    positions: Sequence[float],
    scores: Sequence[float],
) -> str | None:
    """词表情绪走势标签（进度轴前中后切分）；样本不足时 null。"""
    if len(scores) < 3:
        return None
    detail = compute_lexical_emotion_trend_detail(positions, scores)
    trend = detail.get("trend")
    return str(trend) if trend is not None else None
