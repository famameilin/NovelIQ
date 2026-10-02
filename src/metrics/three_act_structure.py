"""
创建时间: 2026-10-02
创建者: Trae
任务: 大文件拆分 src/metrics/narrative_metrics.py（三幕结构算法段）
说明: 承接三幕结构诊断算法——比例归一化、窗口工具、主高潮区识别、
      第一幕边界选择与 analyze_three_act_structure 主入口；数据类与峰值
      基础件从 narrative_primitives 导入，narrative_metrics.py re-export
      analyze_three_act_structure 保持导入方零改动。
"""

from __future__ import annotations

from collections.abc import Sequence

from src.metrics.narrative_primitives import (
    ThreeActBoundaryCandidate,
    ThreeActStructureDiagnostics,
    _validate_position_inputs,
    find_global_peak,
    find_valley_before_peak,
)


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
