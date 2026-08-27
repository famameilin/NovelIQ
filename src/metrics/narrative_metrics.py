from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from src.config import settings


@dataclass(slots=True)
class ThreeActBoundaryCandidate:
    """
    创建时间: 2026-05-02
    任务: three-act-structure-v2
    新建原因: 三幕结构切分需要输出候选边界的关键统计，既供算法选择，
              也供诊断脚本和回放排查直接复用。
    """

    boundary_idx: int
    before_mean_tension: float
    after_mean_tension: float
    before_structure_density: float
    after_structure_density: float
    conflict_count_before: int
    conflict_count_after: int
    plot_flag_count_before: int
    plot_flag_count_after: int
    combined_uplift: float

    def to_dict(self) -> dict[str, float | int]:
        return {
            "boundary_idx": self.boundary_idx,
            "before_mean_tension": round(self.before_mean_tension, 4),
            "after_mean_tension": round(self.after_mean_tension, 4),
            "before_structure_density": round(self.before_structure_density, 4),
            "after_structure_density": round(self.after_structure_density, 4),
            "conflict_count_before": self.conflict_count_before,
            "conflict_count_after": self.conflict_count_after,
            "plot_flag_count_before": self.plot_flag_count_before,
            "plot_flag_count_after": self.plot_flag_count_after,
            "combined_uplift": round(self.combined_uplift, 4),
        }


@dataclass(slots=True)
class ThreeActStructureDiagnostics:
    """
    创建时间: 2026-05-02
    任务: three-act-structure-v2
    新建原因: 三幕比例主链已经升级为“主高潮区 + 结构切分点”，
              需要一个稳定的内部诊断对象，供 aggregate、脚本和回归测试共享。
    """

    act1_ratio: float
    act2_ratio: float
    act3_ratio: float
    climax_region_start: int
    climax_region_end: int
    representative_peak_idx: int
    act1_boundary_idx: int
    boundary_fallback_used: bool
    climax_window_conflicts: int
    climax_window_plot_flags: int
    climax_window_mean_tension: float
    candidate_boundaries: list[ThreeActBoundaryCandidate]

    def ratio_dict(self) -> dict[str, float]:
        return {
            "act1_ratio": self.act1_ratio,
            "act2_ratio": self.act2_ratio,
            "act3_ratio": self.act3_ratio,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.ratio_dict(),
            "climax_region_start": self.climax_region_start,
            "climax_region_end": self.climax_region_end,
            "representative_peak_idx": self.representative_peak_idx,
            "act1_boundary_idx": self.act1_boundary_idx,
            "boundary_fallback_used": self.boundary_fallback_used,
            "climax_window_conflicts": self.climax_window_conflicts,
            "climax_window_plot_flags": self.climax_window_plot_flags,
            "climax_window_mean_tension": round(self.climax_window_mean_tension, 4),
            "candidate_boundaries": [candidate.to_dict() for candidate in self.candidate_boundaries],
        }


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


def _validate_position_inputs(positions: Sequence[float], scores: Sequence[float]) -> None:
    """校验字符坐标版输入的公共前置条件：长度一致且位置严格单调递增。"""
    if len(positions) != len(scores):
        raise ValueError("positions 与 scores 长度必须一致")
    if len(positions) >= 2:
        for prev, curr in zip(positions[:-1], positions[1:], strict=True):
            if curr <= prev:
                raise ValueError("positions 必须严格单调递增")


def find_local_peaks(
    positions: Sequence[float],
    scores: Sequence[float],
    min_spacing: float = 0.05,
) -> list[int]:
    """局部峰值：scores[i] > 邻点且与前峰字符间距 >= min_spacing。"""
    _validate_position_inputs(positions, scores)
    if len(scores) < 3:
        return []
    peaks: list[int] = []
    for i in range(1, len(scores) - 1):
        if scores[i] > scores[i - 1] and scores[i] > scores[i + 1]:
            if not peaks or (positions[i] - positions[peaks[-1]]) >= min_spacing:
                peaks.append(i)
    return peaks


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


def _build_min_ratio_normalized_result(
    act1_raw: float,
    act2_raw: float,
    act3_raw: float,
    min_ratio: float = 0.05,
) -> dict[str, float]:
    """将三幕原始比例按最低占比下限做归一化（2026-08-14 起支持自定义 min_ratio，
    旧调用方不传参时行为不变）。"""
    act1 = max(act1_raw, min_ratio)
    act2 = max(act2_raw, min_ratio)
    act3 = max(act3_raw, min_ratio)
    total_ratio = act1 + act2 + act3
    return {
        "act1_ratio": round(act1 / total_ratio, 4),
        "act2_ratio": round(act2 / total_ratio, 4),
        "act3_ratio": round(act3 / total_ratio, 4),
    }


def _compute_window_mean(scores: list[float], start_idx: int, end_idx: int) -> float:
    window = scores[start_idx:end_idx]
    if not window:
        return 0.0
    return sum(window) / len(window)


def _char_span_of_n_points(positions: Sequence[float], n: int) -> float:
    """返回覆盖前 n 个点所需的字符宽度；点数不足 n 时用全部点，不足 2 点时返回 0.0。"""
    k = min(n, len(positions))
    if k < 2:
        return 0.0
    return positions[k - 1] - positions[0]


def _indices_in_position_range(
    positions: Sequence[float],
    lower: float,
    upper: float,
    *,
    include_lower: bool = True,
    include_upper: bool = False,
) -> list[int]:
    """返回 positions 落在 (lower, upper) 或 [lower, upper) 等区间的索引列表（升序）。"""
    indices: list[int] = []
    for j, position in enumerate(positions):
        in_lower = position >= lower if include_lower else position > lower
        in_upper = position < upper if include_upper else position <= upper
        if in_lower and in_upper:
            indices.append(j)
    return indices


def _select_climax_region(
    positions: Sequence[float],
    event_types: Sequence[str],
    cliffhangers: Sequence[int],
    pivot_moments: Sequence[int],
    tension_scores: Sequence[float],
) -> tuple[int, int, int, int, int, float]:
    """主高潮区识别（§10/§19.8 字符坐标版）：8% 跨度窗口扫描后 45%。"""
    total = len(tension_scores)
    if total == 0:
        return 0, 0, 0, 0, 0, 0.0

    span = positions[-1] - positions[0]
    if span <= 0:
        peak = find_global_peak(list(tension_scores))
        total = len(tension_scores)
        return (
            0,
            total,
            peak,
            0,
            0,
            _compute_window_mean(list(tension_scores), 0, total),
        )

    window_char = max(0.08 * span, _char_span_of_n_points(positions, min(8, total)))
    max_window_char = _char_span_of_n_points(positions, min(24, total))
    if max_window_char > 0:
        window_char = min(window_char, max_window_char)

    scan_start_pos = positions[-1] - 0.45 * span
    last_start_pos = positions[-1] - window_char
    if scan_start_pos > last_start_pos:
        scan_start_pos = last_start_pos
    candidate_starts = [
        i for i in range(total) if positions[i] >= scan_start_pos and positions[i] <= last_start_pos + 1e-9
    ]
    if not candidate_starts:
        # 点过于稀疏：退化为最后一个可放下窗口的起点。
        candidate_starts = [i for i in range(total) if positions[i] <= last_start_pos + 1e-9]
    if not candidate_starts:
        candidate_starts = [total - 1]

    best_start = -1
    best_conflicts = -1
    best_plot_flags = -1
    best_mean_tension = -1.0
    for start_idx in candidate_starts:
        window = _indices_in_position_range(
            positions,
            positions[start_idx],
            positions[start_idx] + window_char,
            include_lower=True,
            include_upper=False,
        )
        if not window:
            continue
        conflict_count = sum(1 for j in window if event_types[j] == "冲突")
        plot_flag_count = sum(cliffhangers[j] for j in window) + sum(pivot_moments[j] for j in window)
        mean_tension = sum(tension_scores[j] for j in window) / len(window)
        candidate_key = (conflict_count, plot_flag_count, mean_tension, start_idx)
        best_key = (best_conflicts, best_plot_flags, best_mean_tension, best_start)
        if candidate_key > best_key:
            best_start = start_idx
            best_conflicts = conflict_count
            best_plot_flags = plot_flag_count
            best_mean_tension = mean_tension

    climax_region_start = best_start
    best_window = _indices_in_position_range(
        positions,
        positions[best_start],
        positions[best_start] + window_char,
        include_lower=True,
        include_upper=False,
    )
    climax_region_end = best_window[-1] + 1 if best_window else min(total, best_start + 1)
    representative_peak_idx = max(
        range(climax_region_start, climax_region_end),
        key=lambda idx: (tension_scores[idx], idx),
    )
    return (
        climax_region_start,
        climax_region_end,
        representative_peak_idx,
        best_conflicts,
        best_plot_flags,
        best_mean_tension,
    )


def _select_act1_boundary(
    positions: Sequence[float],
    event_types: Sequence[str],
    cliffhangers: Sequence[int],
    pivot_moments: Sequence[int],
    tension_scores: Sequence[float],
    *,
    climax_region_start: int,
    representative_peak_idx: int,
) -> tuple[int, bool, list[ThreeActBoundaryCandidate]]:
    """第一幕边界选择（§10/§19.8 字符坐标版）：6% 跨度双窗口择优。"""
    total = len(tension_scores)
    if total < 3:
        return 0, True, []

    span = positions[-1] - positions[0]
    if span <= 0:
        return find_valley_before_peak(list(tension_scores), representative_peak_idx), True, []

    min_window_char = _char_span_of_n_points(positions, min(6, total))
    max_window_char = _char_span_of_n_points(positions, min(18, total))
    window_char = max(0.06 * span, min_window_char)
    if max_window_char > min_window_char:
        window_char = min(window_char, max_window_char)
    if climax_region_start > 0:
        window_char = min(window_char, positions[climax_region_start] - positions[0])
    if window_char <= 0:
        return find_valley_before_peak(list(tension_scores), representative_peak_idx), True, []

    # 第一幕结束点不应早于主高潮区起点的一半（字符中点），且要能放下完整前窗；
    # 也不应紧贴主高潮区，主高潮区前留出两个后窗的缓冲带。
    earliest_boundary_pos = max(
        positions[0] + window_char,
        (positions[0] + positions[climax_region_start]) / 2,
    )
    latest_boundary_pos = positions[climax_region_start] - 2 * window_char

    candidates: list[ThreeActBoundaryCandidate] = []
    for boundary_idx in range(total):
        boundary_pos = positions[boundary_idx]
        if boundary_pos < earliest_boundary_pos or boundary_pos > latest_boundary_pos:
            continue
        before_indices = _indices_in_position_range(
            positions,
            boundary_pos - window_char,
            boundary_pos,
            include_lower=False,
            include_upper=False,
        )
        after_indices = _indices_in_position_range(
            positions,
            boundary_pos,
            boundary_pos + window_char,
            include_lower=True,
            include_upper=False,
        )
        if not before_indices or not after_indices:
            continue
        before_mean_tension = sum(tension_scores[j] for j in before_indices) / len(before_indices)
        after_mean_tension = sum(tension_scores[j] for j in after_indices) / len(after_indices)
        before_conflict_count = sum(1 for j in before_indices if event_types[j] == "冲突")
        after_conflict_count = sum(1 for j in after_indices if event_types[j] == "冲突")
        before_plot_flag_count = sum(cliffhangers[j] for j in before_indices) + sum(
            pivot_moments[j] for j in before_indices
        )
        after_plot_flag_count = sum(cliffhangers[j] for j in after_indices) + sum(
            pivot_moments[j] for j in after_indices
        )
        before_structure_density = (before_conflict_count + before_plot_flag_count) / len(before_indices)
        after_structure_density = (after_conflict_count + after_plot_flag_count) / len(after_indices)
        if after_mean_tension <= before_mean_tension or after_structure_density <= before_structure_density:
            continue

        combined_uplift = (after_mean_tension - before_mean_tension) + (
            after_structure_density - before_structure_density
        )
        candidates.append(
            ThreeActBoundaryCandidate(
                boundary_idx=boundary_idx,
                before_mean_tension=before_mean_tension,
                after_mean_tension=after_mean_tension,
                before_structure_density=before_structure_density,
                after_structure_density=after_structure_density,
                conflict_count_before=before_conflict_count,
                conflict_count_after=after_conflict_count,
                plot_flag_count_before=before_plot_flag_count,
                plot_flag_count_after=after_plot_flag_count,
                combined_uplift=combined_uplift,
            )
        )

    if not candidates:
        return find_valley_before_peak(list(tension_scores), representative_peak_idx), True, []

    best_candidate = max(candidates, key=lambda candidate: (candidate.combined_uplift, -candidate.boundary_idx))
    candidates.sort(key=lambda candidate: (-candidate.combined_uplift, candidate.boundary_idx))
    return best_candidate.boundary_idx, False, candidates


def analyze_three_act_structure(
    positions: Sequence[float],
    event_types: Sequence[str],
    cliffhangers: Sequence[int],
    pivot_moments: Sequence[int],
    tension_scores: Sequence[float],
    min_act_ratio: float = 0.05,
) -> ThreeActStructureDiagnostics:
    """三幕结构诊断（字符进度轴）：8%/6% 窗口选区，字符位置算比例。"""
    _validate_position_inputs(positions, tension_scores)
    if not tension_scores:
        return ThreeActStructureDiagnostics(
            act1_ratio=0.0,
            act2_ratio=0.0,
            act3_ratio=0.0,
            climax_region_start=0,
            climax_region_end=0,
            representative_peak_idx=0,
            act1_boundary_idx=0,
            boundary_fallback_used=True,
            climax_window_conflicts=0,
            climax_window_plot_flags=0,
            climax_window_mean_tension=0.0,
            candidate_boundaries=[],
        )

    total = len(tension_scores)
    span = positions[-1] - positions[0]
    if total < 3 or span <= 0:
        equal_ratio = round(1 / 3, 4)
        return ThreeActStructureDiagnostics(
            act1_ratio=equal_ratio,
            act2_ratio=equal_ratio,
            act3_ratio=equal_ratio,
            climax_region_start=0,
            climax_region_end=max(total - 1, 0),
            representative_peak_idx=find_global_peak(list(tension_scores)),
            act1_boundary_idx=0,
            boundary_fallback_used=True,
            climax_window_conflicts=0,
            climax_window_plot_flags=0,
            climax_window_mean_tension=_compute_window_mean(list(tension_scores), 0, total),
            candidate_boundaries=[],
        )

    (
        climax_region_start,
        climax_region_end,
        representative_peak_idx,
        climax_window_conflicts,
        climax_window_plot_flags,
        climax_window_mean_tension,
    ) = _select_climax_region(
        positions,
        event_types,
        cliffhangers,
        pivot_moments,
        tension_scores,
    )
    act1_boundary_idx, boundary_fallback_used, candidate_boundaries = _select_act1_boundary(
        positions,
        event_types,
        cliffhangers,
        pivot_moments,
        tension_scores,
        climax_region_start=climax_region_start,
        representative_peak_idx=representative_peak_idx,
    )

    act1_raw = (positions[act1_boundary_idx] - positions[0]) / span
    if representative_peak_idx == total - 1:
        act2_raw = (positions[-1] - positions[act1_boundary_idx]) / span
        act3_raw = 0.0
    else:
        act2_raw = (positions[representative_peak_idx] - positions[act1_boundary_idx]) / span
        act3_raw = (positions[-1] - positions[representative_peak_idx]) / span

    ratio_result = _build_min_ratio_normalized_result(act1_raw, act2_raw, act3_raw, min_ratio=min_act_ratio)
    return ThreeActStructureDiagnostics(
        act1_ratio=ratio_result["act1_ratio"],
        act2_ratio=ratio_result["act2_ratio"],
        act3_ratio=ratio_result["act3_ratio"],
        climax_region_start=climax_region_start,
        climax_region_end=climax_region_end,
        representative_peak_idx=representative_peak_idx,
        act1_boundary_idx=act1_boundary_idx,
        boundary_fallback_used=boundary_fallback_used,
        climax_window_conflicts=climax_window_conflicts,
        climax_window_plot_flags=climax_window_plot_flags,
        climax_window_mean_tension=climax_window_mean_tension,
        candidate_boundaries=candidate_boundaries,
    )


def compute_three_act_ratio_v2(
    positions: Sequence[float],
    event_types: list[str],
    cliffhangers: list[int],
    pivot_moments: list[int],
    tension_composite_scores: list[float],
) -> dict[str, float]:
    """三幕比例：归一化字符进度轴。"""
    return analyze_three_act_structure(
        positions,
        event_types,
        cliffhangers,
        pivot_moments,
        tension_composite_scores,
    ).ratio_dict()


def compute_three_act_ratio(
    event_types: list[str],
) -> dict[str, float]:
    return {"act1_ratio": 0.0, "act2_ratio": 0.0, "act3_ratio": 0.0}


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
    """多高潮剖面（§10/§19.8 字符坐标版）：真实位置三位小数。"""
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
