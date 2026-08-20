"""时间轴阶段共享逻辑（从 timeline_metrics 抽取，供事件森林复用）"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from loguru import logger

from src.metrics.narrative_metrics import find_global_peak, find_local_peaks

TimelinePhaseName = Literal["引入期", "发展期", "高潮期", "收束期"]


@dataclass(slots=True)
class TimelinePhaseDTO:
    """时间轴阶段 DTO"""

    name: TimelinePhaseName
    start: int
    end: int
    ratio: float


@dataclass(slots=True)
class NarrativePhase:
    """叙事阶段内部数据结构"""

    name: str
    start: int
    end: int
    ratio: float


def calculate_tension_percentile(
    tension_score: float,
    all_tensions: list[float],
) -> int:
    if not all_tensions:
        return 50
    count_le = sum(1 for tension in all_tensions if tension <= tension_score)
    percentile = int((count_le / len(all_tensions)) * 100)
    return min(percentile, 100)


def compute_four_phases(
    tension_scores: list[float],
    chapter_ids: list[int],
    positions: list[float] | None = None,
) -> list[NarrativePhase]:
    if not tension_scores or not chapter_ids:
        return []
    total = len(tension_scores)
    min_phase_length = 1
    if total < 20:
        boundary_1 = max(1, min(int(total * 0.15), total - 3))
        boundary_2 = max(boundary_1 + 1, min(int(total * 0.50), total - 2))
        boundary_3 = max(boundary_2 + 1, min(int(total * 0.80), total - 2))
        if total < 5:
            return [
                NarrativePhase(
                    "引入期",
                    chapter_ids[0],
                    chapter_ids[-1],
                    1.0,
                )
            ]
        return [
            NarrativePhase("引入期", chapter_ids[0], chapter_ids[boundary_1], (boundary_1 + 1) / total),
            NarrativePhase(
                "发展期",
                chapter_ids[boundary_1 + 1],
                chapter_ids[boundary_2],
                (boundary_2 - boundary_1) / total,
            ),
            NarrativePhase(
                "高潮期",
                chapter_ids[boundary_2 + 1],
                chapter_ids[boundary_3],
                (boundary_3 - boundary_2) / total,
            ),
            NarrativePhase("收束期", chapter_ids[boundary_3 + 1], chapter_ids[-1], (total - boundary_3 - 1) / total),
        ]
    if positions is None or len(positions) != total:
        positions = [i / max(total - 1, 1) for i in range(total)]
    local_peaks = find_local_peaks(positions, tension_scores)
    half_progress = 0.5
    if local_peaks:
        late_peaks = [peak for peak in local_peaks if positions[peak] >= half_progress]
        if late_peaks:
            peak_idx = max(late_peaks, key=lambda idx: tension_scores[idx])
        else:
            peak_idx = local_peaks[-1]
    else:
        logger.warning("No local peaks found in tension_scores, falling back to global peak")
        peak_idx = find_global_peak(tension_scores)
    if peak_idx == 0:
        valley_idx = max(min_phase_length, int(total * 0.15))
    else:
        before_peak = tension_scores[:peak_idx]
        valley_idx = max(min_phase_length, min(range(len(before_peak)), key=lambda idx: before_peak[idx]))
    max_climax_radius = int(total * 0.10)
    climax_radius = min(max(3, int(total * 0.05)), max_climax_radius)
    climax_start = max(valley_idx + min_phase_length, peak_idx - climax_radius)
    climax_end = min(total - 1 - min_phase_length, peak_idx + climax_radius)
    if climax_start > climax_end:
        climax_start = min(valley_idx + min_phase_length, total - 1)
        climax_end = climax_start
    valley_idx = min(valley_idx, climax_start - min_phase_length)
    valley_idx = max(valley_idx, min_phase_length)
    phases: list[NarrativePhase] = []
    phases.append(NarrativePhase("引入期", chapter_ids[0], chapter_ids[valley_idx], (valley_idx + 1) / total))
    dev_start_idx = valley_idx + 1
    dev_end_idx = climax_start - 1
    if dev_end_idx >= dev_start_idx:
        phases.append(
            NarrativePhase(
                "发展期",
                chapter_ids[dev_start_idx],
                chapter_ids[dev_end_idx],
                (dev_end_idx - dev_start_idx + 1) / total,
            )
        )
    else:
        phases.append(NarrativePhase("发展期", chapter_ids[valley_idx], chapter_ids[valley_idx], 0.0))
    phases.append(
        NarrativePhase(
            "高潮期",
            chapter_ids[climax_start],
            chapter_ids[climax_end],
            (climax_end - climax_start + 1) / total,
        )
    )
    if climax_end < total - 1 - min_phase_length:
        phases.append(
            NarrativePhase(
                "收束期",
                chapter_ids[climax_end + 1],
                chapter_ids[-1],
                (total - climax_end - 1) / total,
            )
        )
    else:
        phases.append(
            NarrativePhase(
                "收束期",
                chapter_ids[climax_end + 1],
                chapter_ids[-1],
                (total - climax_end - 1) / total,
            )
        )
    return phases


def convert_to_timeline_phases(phases: list[NarrativePhase]) -> list[TimelinePhaseDTO]:
    result: list[TimelinePhaseDTO] = []
    for phase in phases:
        if phase.name in ("引入期", "发展期", "高潮期", "收束期"):
            name = cast(TimelinePhaseName, phase.name)
        else:
            name = "引入期"
        result.append(TimelinePhaseDTO(name=name, start=phase.start, end=phase.end, ratio=round(phase.ratio, 4)))
    return result
