from __future__ import annotations

import statistics
from collections import Counter
from typing import Dict, List, Optional, Tuple


def compute_emotion_recovery_speed(
    emotion_values: List[float],
    threshold: float | None = None,
) -> Optional[float]:
    """Compute the average distance from a negative dip back toward baseline."""
    if not emotion_values:
        return None

    if threshold is None:
        if len(emotion_values) > 1:
            std_dev = statistics.stdev(emotion_values)
            threshold = max(std_dev * 0.5, 0.005)
        else:
            threshold = 0.005

    baseline = sum(emotion_values) / len(emotion_values)

    recovery_distances = []
    for i, val in enumerate(emotion_values):
        if val < baseline - threshold:
            for j in range(i + 1, len(emotion_values)):
                if emotion_values[j] >= baseline - threshold * 0.5:
                    recovery_distances.append(j - i)
                    break

    if not recovery_distances:
        return None

    return sum(recovery_distances) / len(recovery_distances)


def compute_emotion_polarity_distribution(
    emotional_valences: List[str],
) -> Dict[str, float]:
    """Compute positive, negative, and neutral valence ratios."""
    if not emotional_valences:
        return {"positive_ratio": 0.0, "negative_ratio": 0.0, "neutral_ratio": 0.0}

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
    pivot_moments: List[int],
) -> float:
    if not pivot_moments:
        return 0.0

    return sum(pivot_moments) / len(pivot_moments)


def compute_lexical_emotion_trend(
    emotion_values: List[float],
) -> str:
    """Classify lexicon-based emotion trend as rising, falling, stable, or volatile."""
    if len(emotion_values) < 3:
        return "stable"

    n = len(emotion_values)
    third = n // 3

    first_segment = emotion_values[:third]
    last_segment = emotion_values[2 * third :]

    first_avg = sum(first_segment) / len(first_segment) if first_segment else 0.0
    last_avg = sum(last_segment) / len(last_segment) if last_segment else 0.0

    stdev = statistics.stdev(emotion_values) if len(emotion_values) > 1 else 0.0
    diff = last_avg - first_avg

    if stdev >= 0.003:
        return "volatile"
    if diff > 0.002:
        return "rising"
    if diff < -0.002:
        return "falling"
    return "stable"


def compute_arc_delta(
    character_emotion_scores: List[Tuple[str, List[float]]],
) -> float:
    if not character_emotion_scores:
        return 0.0

    stds = []
    for _, scores in character_emotion_scores:
        if len(scores) >= 2:
            stds.append(statistics.stdev(scores))

    return sum(stds) / len(stds) if stds else 0.0


def compute_pos_neg_ratio(
    pos_densities: List[float],
    neg_densities: List[float],
) -> float:
    if not pos_densities and not neg_densities:
        return 0.0

    pos_sum = sum(pos_densities) if pos_densities else 0.0
    neg_sum = sum(neg_densities) if neg_densities else 0.0

    return pos_sum / (neg_sum + 1e-6)
