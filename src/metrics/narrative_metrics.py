from __future__ import annotations

from collections import Counter

from src.config import settings


def find_global_peak(scores: list[float]) -> int:
    if not scores:
        return 0
    return max(range(len(scores)), key=lambda i: scores[i])


def find_valley_before_peak(scores: list[float], peak_idx: int) -> int:
    if peak_idx == 0:
        return 0
    before_peak = scores[:peak_idx]
    if not before_peak:
        return 0
    return min(range(len(before_peak)), key=lambda i: before_peak[i])


def find_local_peaks(scores: list[float], total_chunks: int) -> list[int]:
    if not scores or total_chunks == 0:
        return []
    min_distance = max(10, int(total_chunks * 0.05))
    peaks: list[int] = []
    for i in range(1, len(scores) - 1):
        if scores[i] > scores[i - 1] and scores[i] > scores[i + 1]:
            if not peaks or (i - peaks[-1]) >= min_distance:
                peaks.append(i)
    return peaks


def find_dominant_climax_peak(scores: list[float]) -> int:
    """
    2026-04-28，任务：三幕比例主高潮峰修复
    新建原因：三幕比例如果只取全局最高峰，容易被前段尖峰误判成“主高潮”，
    导致后续真正的高潮与收束被整体压扁；这里独立从张力曲线中选择更符合
    叙事结构语义的主高潮峰，不直接依赖时间轴阶段结果。
    """
    if not scores:
        return 0

    total = len(scores)
    if total < 3:
        return find_global_peak(scores)

    local_peaks = find_local_peaks(scores, total)
    if not local_peaks:
        return find_global_peak(scores)

    half_idx = total // 2
    late_peaks = [peak_idx for peak_idx in local_peaks if peak_idx >= half_idx]
    if late_peaks:
        return max(late_peaks, key=lambda peak_idx: (scores[peak_idx], peak_idx))

    return local_peaks[-1]


def compute_three_act_ratio_by_tension(
    tension_composite_scores: list[float],
) -> dict[str, float]:
    """
    2026-04-28，任务：三幕比例主高潮峰修复
    修改原因：当前输入的 `tension_composite_scores` 已经在 aggregate 阶段完成
    一次平滑；这里若再做二次平滑，会把后段真正主高潮继续削峰，进而把三幕
    比例误判成“前段极短 + 后段几乎全是收束”。

    当前实现保持三幕比例独立于 timeline 结果计算，但主高潮峰不再使用
    “全局最高峰”这一过于脆弱的规则，而是优先在后半段局部峰中选择最能代表
    最终高潮的峰位，保留与时间轴互相校验的能力。
    """
    if not tension_composite_scores:
        return {"act1_ratio": 0.0, "act2_ratio": 0.0, "act3_ratio": 0.0}

    total = len(tension_composite_scores)
    if total < 3:
        return {"act1_ratio": 1 / 3, "act2_ratio": 1 / 3, "act3_ratio": 1 / 3}

    peak_idx = find_dominant_climax_peak(tension_composite_scores)
    valley_idx = find_valley_before_peak(tension_composite_scores, peak_idx)

    act1_raw = valley_idx / total
    if peak_idx == total - 1:
        act2_raw = (total - valley_idx) / total
        act3_raw = 0.0
    else:
        act2_raw = (peak_idx - valley_idx) / total
        act3_raw = (total - peak_idx) / total

    MIN_RATIO = 0.05
    act1 = max(act1_raw, MIN_RATIO)
    act2 = max(act2_raw, MIN_RATIO)
    act3 = max(act3_raw, MIN_RATIO)

    total_ratio = act1 + act2 + act3
    return {
        "act1_ratio": round(act1 / total_ratio, 4),
        "act2_ratio": round(act2 / total_ratio, 4),
        "act3_ratio": round(act3 / total_ratio, 4),
    }


def compute_three_act_ratio(
    event_types: list[str],
) -> dict[str, float]:
    return {"act1_ratio": 0.0, "act2_ratio": 0.0, "act3_ratio": 0.0}


def compute_climax_spacing(
    chunk_ids: list[int],
    tension_composite_scores: list[float],
) -> float:
    if not chunk_ids or not tension_composite_scores:
        return 0.0
    if len(chunk_ids) != len(tension_composite_scores):
        return 0.0

    peak_indices = find_local_peaks(tension_composite_scores, len(chunk_ids))

    if len(peak_indices) < 2:
        return 0.0

    spacings = []
    for i in range(1, len(peak_indices)):
        spacing = chunk_ids[peak_indices[i]] - chunk_ids[peak_indices[i - 1]]
        spacings.append(spacing)

    return sum(spacings) / len(spacings) if spacings else 0.0


def compute_middle_collapse_index(
    chunk_ids: list[int],
    tension_composite_scores: list[float],
) -> float:
    if not chunk_ids or not tension_composite_scores:
        return 0.0

    if len(chunk_ids) != len(tension_composite_scores):
        return 0.0

    total = len(chunk_ids)
    if total < settings.metrics.middle_collapse_min_chunks:
        return 0.0

    start_idx = int(total * 0.3)
    end_idx = int(total * 0.7)

    def compute_avg_score(indices: range) -> float:
        scores = [tension_composite_scores[i] for i in indices if i < len(tension_composite_scores)]
        return sum(scores) / len(scores) if scores else 0.0

    head_score = compute_avg_score(range(0, start_idx))
    middle_score = compute_avg_score(range(start_idx, end_idx))
    tail_score = compute_avg_score(range(end_idx, total))

    head_tail_avg = (head_score + tail_score) / 2
    if head_tail_avg == 0:
        return 0.0

    return middle_score / head_tail_avg


def compute_event_density(
    event_types: list[str],
) -> dict[str, float]:
    valid_types = ["冲突", "铺垫", "转折"]
    if not event_types:
        return dict.fromkeys(valid_types, 0.0)

    counts = Counter(et for et in event_types if et in valid_types)
    total = len(event_types)

    return {et: counts.get(et, 0) / total for et in valid_types}


def compute_cliffhanger_rate(
    cliffhangers: list[int],
) -> float:
    if not cliffhangers:
        return 0.0

    return sum(cliffhangers) / len(cliffhangers)


def compute_climax_profile(
    tension_composite_scores: list[float],
) -> dict:
    """
    计算多高潮剖面

    在 climax_interval 的基础上增加分布信息，作为三幕比例的补充指标

    返回字段:
    - climax_count: 高潮数量
    - climax_positions: 各高潮位于全书的百分比位置
    - climax_heights: 各高潮的张力值（归一化）
    - peak_escalation: 是否逐步升级（ascending/descending/flat）
    - dominant_climax_pos: 最强高潮的位置百分比
    """
    if not tension_composite_scores:
        return {
            "climax_count": 0,
            "climax_positions": [],
            "climax_heights": [],
            "peak_escalation": None,
            "dominant_climax_pos": None,
        }

    total = len(tension_composite_scores)
    peaks = find_local_peaks(tension_composite_scores, total)

    if not peaks:
        return {
            "climax_count": 0,
            "climax_positions": [],
            "climax_heights": [],
            "peak_escalation": None,
            "dominant_climax_pos": None,
        }

    max_val = max(tension_composite_scores)
    if max_val == 0:
        max_val = 1.0

    positions = [round(p / total, 3) for p in peaks]
    heights = [round(tension_composite_scores[p] / max_val, 3) for p in peaks]

    escalation = None
    if len(heights) >= 3:
        xs = list(range(len(heights)))
        mean_x = sum(xs) / len(xs)
        mean_y = sum(heights) / len(heights)
        numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, heights, strict=True))
        denominator = sum((x - mean_x) ** 2 for x in xs)
        if denominator > 0:
            slope = numerator / denominator
            if slope > 0.05:
                escalation = "ascending"
            elif slope < -0.05:
                escalation = "descending"
            else:
                escalation = "flat"

    dominant_idx = heights.index(max(heights))
    dominant_pos = positions[dominant_idx]

    return {
        "climax_count": len(peaks),
        "climax_positions": positions,
        "climax_heights": heights,
        "peak_escalation": escalation,
        "dominant_climax_pos": dominant_pos,
    }
