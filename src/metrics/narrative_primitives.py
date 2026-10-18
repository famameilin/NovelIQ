"""
三幕结构数据类与峰值基础工具

承接 ThreeActBoundaryCandidate/ThreeActStructureDiagnostics 与全局峰值/谷值、
局部峰值、坐标输入校验等基础工具；供 three_act_structure.py、
narrative_metrics.py 与 timeline_phase.py 复用。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(slots=True)
class ThreeActBoundaryCandidate:
    """三幕结构候选边界的关键统计，供算法选择、诊断脚本与回放排查复用。"""

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
    """三幕结构诊断对象（主高潮区 + 结构切分点），供 aggregate、脚本与回归测试共享。"""

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
