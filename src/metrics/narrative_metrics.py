from __future__ import annotations

from collections import Counter
from typing import Dict, List

from src.config import settings


def find_global_peak(scores: List[float]) -> int:
    if not scores:
        return 0
    return max(range(len(scores)), key=lambda i: scores[i])


def find_valley_before_peak(scores: List[float], peak_idx: int) -> int:
    if peak_idx == 0:
        return 0
    before_peak = scores[:peak_idx]
    if not before_peak:
        return 0
    return min(range(len(before_peak)), key=lambda i: before_peak[i])


def find_local_peaks(scores: List[float], total_chunks: int) -> List[int]:
    if not scores or total_chunks == 0:
        return []
    min_distance = max(10, int(total_chunks * 0.05))
    peaks: List[int] = []
    for i in range(1, len(scores) - 1):
        if scores[i] > scores[i - 1] and scores[i] > scores[i + 1]:
            if not peaks or (i - peaks[-1]) >= min_distance:
                peaks.append(i)
    return peaks


def compute_three_act_ratio_by_tension(
    tension_composite_scores: List[float],
) -> Dict[str, float]:
    if not tension_composite_scores:
        return {"act1_ratio": 0.0, "act2_ratio": 0.0, "act3_ratio": 0.0}

    total = len(tension_composite_scores)
    peak_idx = find_global_peak(tension_composite_scores)
    valley_idx = find_valley_before_peak(tension_composite_scores, peak_idx)

    act1 = valley_idx / total
    if peak_idx == total - 1:
        act2 = (total - valley_idx) / total
        act3 = 0.0
    else:
        act2 = (peak_idx - valley_idx) / total
        act3 = (total - peak_idx) / total

    return {
        "act1_ratio": act1,
        "act2_ratio": act2,
        "act3_ratio": act3,
    }


def compute_three_act_ratio(
    event_types: List[str],
) -> Dict[str, float]:
    return {"act1_ratio": 0.0, "act2_ratio": 0.0, "act3_ratio": 0.0}


def compute_climax_spacing(
    chunk_ids: List[int],
    tension_composite_scores: List[float],
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
    chunk_ids: List[int],
    tension_composite_scores: List[float],
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
    event_types: List[str],
) -> Dict[str, float]:
    valid_types = ["冲突", "铺垫", "转折"]
    if not event_types:
        return {et: 0.0 for et in valid_types}

    counts = Counter(et for et in event_types if et in valid_types)
    total = len(event_types)

    return {et: counts.get(et, 0) / total for et in valid_types}


def compute_cliffhanger_rate(
    cliffhangers: List[int],
) -> float:
    if not cliffhangers:
        return 0.0

    return sum(cliffhangers) / len(cliffhangers)
