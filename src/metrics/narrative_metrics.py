from __future__ import annotations

from collections import Counter
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


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


def _build_min_ratio_normalized_result(
    act1_raw: float,
    act2_raw: float,
    act3_raw: float,
) -> dict[str, float]:
    min_ratio = 0.05
    act1 = max(act1_raw, min_ratio)
    act2 = max(act2_raw, min_ratio)
    act3 = max(act3_raw, min_ratio)
    total_ratio = act1 + act2 + act3
    return {
        "act1_ratio": round(act1 / total_ratio, 4),
        "act2_ratio": round(act2 / total_ratio, 4),
        "act3_ratio": round(act3 / total_ratio, 4),
    }


def _count_conflicts(event_types: list[str], start_idx: int, end_idx: int) -> int:
    return sum(1 for event_type in event_types[start_idx:end_idx] if event_type == "冲突")


def _count_plot_flags(cliffhangers: list[int], pivot_moments: list[int], start_idx: int, end_idx: int) -> int:
    return sum(cliffhangers[start_idx:end_idx]) + sum(pivot_moments[start_idx:end_idx])


def _compute_structure_density(
    event_types: list[str],
    cliffhangers: list[int],
    pivot_moments: list[int],
    start_idx: int,
    end_idx: int,
) -> tuple[float, int, int]:
    window_len = max(end_idx - start_idx, 1)
    conflict_count = _count_conflicts(event_types, start_idx, end_idx)
    plot_flag_count = _count_plot_flags(cliffhangers, pivot_moments, start_idx, end_idx)
    density = (conflict_count + plot_flag_count) / window_len
    return density, conflict_count, plot_flag_count


def _compute_window_mean(scores: list[float], start_idx: int, end_idx: int) -> float:
    window = scores[start_idx:end_idx]
    if not window:
        return 0.0
    return sum(window) / len(window)


def _select_climax_region(
    event_types: list[str],
    cliffhangers: list[int],
    pivot_moments: list[int],
    tension_composite_scores: list[float],
) -> tuple[int, int, int, int, float]:
    """
    创建时间: 2026-05-02
    任务: three-act-structure-v2
    新建原因: 正式三幕口径先识别后段主高潮区，再从区内选代表峰，
              不能继续把单个数值峰直接当成完整高潮结构。
    """
    total = len(tension_composite_scores)
    if total == 0:
        return 0, 0, 0, 0, 0.0

    window_size = min(total, _clamp(round(total * 0.08), 8, 24))
    late_window_span = max(1, round(total * 0.45))
    scan_start = max(0, total - late_window_span)
    last_start = max(0, total - window_size)
    if scan_start > last_start:
        scan_start = last_start

    best_start = scan_start
    best_conflicts = -1
    best_plot_flags = -1
    best_mean_tension = -1.0
    for start_idx in range(scan_start, last_start + 1):
        end_idx = start_idx + window_size
        conflict_count = _count_conflicts(event_types, start_idx, end_idx)
        plot_flag_count = _count_plot_flags(cliffhangers, pivot_moments, start_idx, end_idx)
        mean_tension = _compute_window_mean(tension_composite_scores, start_idx, end_idx)
        candidate_key = (conflict_count, plot_flag_count, mean_tension, start_idx)
        best_key = (best_conflicts, best_plot_flags, best_mean_tension, best_start)
        if candidate_key > best_key:
            best_start = start_idx
            best_conflicts = conflict_count
            best_plot_flags = plot_flag_count
            best_mean_tension = mean_tension

    climax_region_start = best_start
    climax_region_end = min(total, best_start + window_size)
    representative_peak_idx = max(
        range(climax_region_start, climax_region_end),
        key=lambda idx: (tension_composite_scores[idx], idx),
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
    event_types: list[str],
    cliffhangers: list[int],
    pivot_moments: list[int],
    tension_composite_scores: list[float],
    *,
    climax_region_start: int,
    representative_peak_idx: int,
) -> tuple[int, bool, list[ThreeActBoundaryCandidate]]:
    """
    创建时间: 2026-05-02
    任务: three-act-structure-v2
    新建原因: 第一幕结束点不再取峰前绝对最低谷，而是选能稳定识别“进入持续上升段”的结构切分点。
    """
    total = len(tension_composite_scores)
    if total < 3:
        return 0, True, []

    boundary_window_size = min(max(climax_region_start, 1), _clamp(round(total * 0.06), 6, 18))
    if boundary_window_size <= 0:
        return find_valley_before_peak(tension_composite_scores, representative_peak_idx), True, []

    candidates: list[ThreeActBoundaryCandidate] = []
    # 中文注释：三幕里的第一幕结束点不应早于主高潮区起点的一半，
    # 否则前段任意一次小抬升都可能被误判成“正式进入第二幕”。
    earliest_boundary = max(boundary_window_size, climax_region_start // 2)
    # 中文注释：第一幕结束点不应该落到“紧贴主高潮区”的最后一跳上，
    # 因此给主高潮区前再留出一个完整后窗缓冲带，避免边界直接吃进第三幕前沿。
    latest_boundary = climax_region_start - (2 * boundary_window_size)
    for boundary_idx in range(earliest_boundary, latest_boundary + 1):
        before_start = boundary_idx - boundary_window_size
        before_end = boundary_idx
        after_start = boundary_idx
        after_end = boundary_idx + boundary_window_size
        before_mean_tension = _compute_window_mean(tension_composite_scores, before_start, before_end)
        after_mean_tension = _compute_window_mean(tension_composite_scores, after_start, after_end)
        before_structure_density, conflict_before, plot_flag_before = _compute_structure_density(
            event_types,
            cliffhangers,
            pivot_moments,
            before_start,
            before_end,
        )
        after_structure_density, conflict_after, plot_flag_after = _compute_structure_density(
            event_types,
            cliffhangers,
            pivot_moments,
            after_start,
            after_end,
        )
        if after_mean_tension <= before_mean_tension or after_structure_density <= before_structure_density:
            continue

        combined_uplift = (
            (after_mean_tension - before_mean_tension)
            + (after_structure_density - before_structure_density)
        )
        candidates.append(
            ThreeActBoundaryCandidate(
                boundary_idx=boundary_idx,
                before_mean_tension=before_mean_tension,
                after_mean_tension=after_mean_tension,
                before_structure_density=before_structure_density,
                after_structure_density=after_structure_density,
                conflict_count_before=conflict_before,
                conflict_count_after=conflict_after,
                plot_flag_count_before=plot_flag_before,
                plot_flag_count_after=plot_flag_after,
                combined_uplift=combined_uplift,
            )
        )

    if not candidates:
        return find_valley_before_peak(tension_composite_scores, representative_peak_idx), True, []

    best_candidate = max(candidates, key=lambda candidate: (candidate.combined_uplift, -candidate.boundary_idx))
    candidates.sort(key=lambda candidate: (-candidate.combined_uplift, candidate.boundary_idx))
    return best_candidate.boundary_idx, False, candidates


def analyze_three_act_structure(
    event_types: list[str],
    cliffhangers: list[int],
    pivot_moments: list[int],
    tension_composite_scores: list[float],
) -> ThreeActStructureDiagnostics:
    """
    创建时间: 2026-05-02
    任务: three-act-structure-v2
    新建原因: aggregate 主链需要从现有注解信号和张力曲线联合计算三幕比例，
              并保留可解释的主高潮区与结构切分点诊断结果。
    """
    if not tension_composite_scores:
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

    total = len(tension_composite_scores)
    if total < 3:
        equal_ratio = round(1 / 3, 4)
        return ThreeActStructureDiagnostics(
            act1_ratio=equal_ratio,
            act2_ratio=equal_ratio,
            act3_ratio=equal_ratio,
            climax_region_start=0,
            climax_region_end=max(total - 1, 0),
            representative_peak_idx=find_global_peak(tension_composite_scores),
            act1_boundary_idx=0,
            boundary_fallback_used=True,
            climax_window_conflicts=0,
            climax_window_plot_flags=0,
            climax_window_mean_tension=_compute_window_mean(tension_composite_scores, 0, total),
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
        event_types,
        cliffhangers,
        pivot_moments,
        tension_composite_scores,
    )
    act1_boundary_idx, boundary_fallback_used, candidate_boundaries = _select_act1_boundary(
        event_types,
        cliffhangers,
        pivot_moments,
        tension_composite_scores,
        climax_region_start=climax_region_start,
        representative_peak_idx=representative_peak_idx,
    )

    act1_raw = act1_boundary_idx / total
    if representative_peak_idx == total - 1:
        act2_raw = (total - act1_boundary_idx) / total
        act3_raw = 0.0
    else:
        act2_raw = (representative_peak_idx - act1_boundary_idx) / total
        act3_raw = (total - representative_peak_idx) / total

    ratio_result = _build_min_ratio_normalized_result(act1_raw, act2_raw, act3_raw)
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
    event_types: list[str],
    cliffhangers: list[int],
    pivot_moments: list[int],
    tension_composite_scores: list[float],
) -> dict[str, float]:
    """
    创建时间: 2026-05-02
    任务: three-act-structure-v2
    新建原因: aggregate 主链需要三幕比例新口径，但保留旧的单曲线函数给回归对照和简单调用方。
    """
    return analyze_three_act_structure(
        event_types,
        cliffhangers,
        pivot_moments,
        tension_composite_scores,
    ).ratio_dict()


def compute_three_act_ratio_by_tension(
    tension_composite_scores: list[float],
) -> dict[str, float]:
    """
    2026-04-28，任务：三幕比例主高潮峰修复
    修改原因：当前输入的 `tension_composite_scores` 已经在 aggregate 阶段完成
    一次平滑；这里若再做二次平滑，会把后段真正主高潮继续削峰，进而把三幕
    比例误判成“前段极短 + 后段几乎全是收束”。

    当前函数保留旧口径，供轻量调用方与回归测试对照使用；
    aggregate 主链已升级到 `compute_three_act_ratio_v2()`。
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

    return _build_min_ratio_normalized_result(act1_raw, act2_raw, act3_raw)


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
