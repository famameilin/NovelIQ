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


def compute_three_act_ratio_by_tension(
    tension_composite_scores: list[float],
) -> dict[str, float]:
    """
    计算三幕比例

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: 预处理流程
    说明: 基于 Freytag 金字塔理论，通过张力峰值位置确定三幕边界

    修改时间: 2026-03-28
    修改者: TraeAI
    任务: 叙事时间轴功能设计评估
    修改内容: 增加边界保护（最小比例 5%）+ 归一化，处理单调序列、峰在开头/结尾等退化场景

    理论依据:
    - Act1 = 开始 → 峰前谷底（铺垫期，张力积累前的平静）
    - Act2 = 谷底 → 全局峰值（上升期+高潮，张力爬坡）
    - Act3 = 峰值 → 结束（收束期）
    - 典型黄金比例: 25%–50%–25%
    """
    if not tension_composite_scores:
        return {"act1_ratio": 0.0, "act2_ratio": 0.0, "act3_ratio": 0.0}

    total = len(tension_composite_scores)
    if total < 3:
        return {"act1_ratio": 1 / 3, "act2_ratio": 1 / 3, "act3_ratio": 1 / 3}

    peak_idx = find_global_peak(tension_composite_scores)
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

    创建时间: 2026-03-28
    创建者: TraeAI
    任务: 叙事时间轴功能设计评估
    说明: 在 climax_interval 的基础上增加分布信息，作为三幕比例的补充指标

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
