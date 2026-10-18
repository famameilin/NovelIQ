"""
叙事曲线指标入口

本模块保留独立曲线指标（高潮间距/中段塌陷/事件密度/悬念率/高潮剖面）；
数据类与峰值工具在 narrative_primitives.py、三幕结构诊断在
three_act_structure.py，并在此 re-export。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from src.config import settings
from src.metrics.narrative_primitives import (
    ThreeActBoundaryCandidate as ThreeActBoundaryCandidate,
)
from src.metrics.narrative_primitives import (
    ThreeActStructureDiagnostics as ThreeActStructureDiagnostics,
)
from src.metrics.narrative_primitives import (
    _validate_position_inputs,
    find_local_peaks,
)
from src.metrics.narrative_primitives import (
    find_global_peak as find_global_peak,
)
from src.metrics.narrative_primitives import (
    find_valley_before_peak as find_valley_before_peak,
)
from src.metrics.three_act_structure import analyze_three_act_structure as analyze_three_act_structure


def compute_climax_spacing(
    positions: Sequence[float],
    tension_scores: Sequence[float],
) -> float | None:
    """高潮间距：相邻峰的归一化进度差均值；峰 <2 时 null。"""
    if not positions or not tension_scores:
        return None
    if len(positions) != len(tension_scores):
        return None
    _validate_position_inputs(positions, tension_scores)

    peak_indices = find_local_peaks(positions, tension_scores)
    if len(peak_indices) < 2:
        return None

    spacings = [positions[peak_indices[i]] - positions[peak_indices[i - 1]] for i in range(1, len(peak_indices))]
    return sum(spacings) / len(spacings) if spacings else None


def compute_middle_collapse_index(
    positions: Sequence[float],
    tension_scores: Sequence[float],
) -> float | None:
    """中段塌陷：进度 [0.3,0.7) 区间均值 / 首尾区间均值。"""
    if not positions or not tension_scores:
        return None
    if len(positions) != len(tension_scores):
        return None
    if len(positions) < settings.metrics.middle_collapse_min_chunks:
        return None
    _validate_position_inputs(positions, tension_scores)

    span = positions[-1] - positions[0]
    if span <= 0:
        return None

    def avg_in_range(lo: float, hi: float) -> float | None:
        vals = [tension_scores[i] for i, pos in enumerate(positions) if lo <= (pos - positions[0]) / span < hi]
        if not vals:
            return None
        return sum(vals) / len(vals)

    head = avg_in_range(0.0, 0.3)
    middle = avg_in_range(0.3, 0.7)
    tail = avg_in_range(0.7, 1.0000001)
    if head is None or middle is None or tail is None:
        return None
    head_tail_avg = (head + tail) / 2
    if head_tail_avg == 0:
        return None
    return middle / head_tail_avg


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
    positions: Sequence[float],
    tension_scores: Sequence[float],
) -> dict:
    """多高潮剖面（字符坐标版）：真实位置三位小数。"""
    if not tension_scores:
        return {
            "climax_count": 0,
            "climax_positions": [],
            "climax_heights": [],
            "peak_escalation": None,
            "dominant_climax_pos": None,
        }
    _validate_position_inputs(positions, tension_scores)

    peaks = find_local_peaks(positions, tension_scores)

    if not peaks:
        return {
            "climax_count": 0,
            "climax_positions": [],
            "climax_heights": [],
            "peak_escalation": None,
            "dominant_climax_pos": None,
        }

    max_val = max(tension_scores)
    if max_val == 0:
        max_val = 1.0

    climax_positions = [round(positions[p], 3) for p in peaks]
    heights = [round(tension_scores[p] / max_val, 3) for p in peaks]

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
    dominant_pos = climax_positions[dominant_idx]

    return {
        "climax_count": len(peaks),
        "climax_positions": climax_positions,
        "climax_heights": heights,
        "peak_escalation": escalation,
        "dominant_climax_pos": dominant_pos,
    }
