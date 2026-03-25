"""Compatibility wrapper for aggregate metrics package."""

from __future__ import annotations

import warnings

from src.metrics.aggregate import (
    AggregateResult,
    AnnotationData,
    CharacterData,
    CultureData,
    EmotionData,
    RelationData,
    TensionData,
    TextData,
    compute_character_relation_metrics,
    compute_emotion_curve_metrics,
    compute_language_style_metrics,
    compute_narrative_structure_metrics,
    compute_traditional_culture_metrics,
    fetch_annotation_data,
    fetch_character_data,
    fetch_culture_data,
    fetch_emotion_data,
    fetch_relation_data,
    fetch_tension_data,
    fetch_text_data,
)
from src.metrics.aggregate.types import map_emotion_score


def _deprecated_alias(old_name: str, new_func):
    """Create a deprecated alias for backwards compatibility."""

    def wrapper(*args, **kwargs):
        warnings.warn(
            f"{old_name} is deprecated. Use {new_func.__name__} instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return new_func(*args, **kwargs)

    wrapper.__name__ = old_name
    wrapper.__doc__ = f"Deprecated. Use {new_func.__name__} instead."
    return wrapper


_fetch_annotation_data = _deprecated_alias("_fetch_annotation_data", fetch_annotation_data)
_fetch_emotion_data = _deprecated_alias("_fetch_emotion_data", fetch_emotion_data)
_fetch_character_data = _deprecated_alias("_fetch_character_data", fetch_character_data)
_fetch_relation_data = _deprecated_alias("_fetch_relation_data", fetch_relation_data)
_fetch_text_data = _deprecated_alias("_fetch_text_data", fetch_text_data)
_fetch_culture_data = _deprecated_alias("_fetch_culture_data", fetch_culture_data)
_fetch_tension_data = _deprecated_alias("_fetch_tension_data", fetch_tension_data)
_compute_narrative_structure_metrics = _deprecated_alias(
    "_compute_narrative_structure_metrics", compute_narrative_structure_metrics
)
_compute_emotion_curve_metrics = _deprecated_alias(
    "_compute_emotion_curve_metrics", compute_emotion_curve_metrics
)
_compute_character_relation_metrics = _deprecated_alias(
    "_compute_character_relation_metrics", compute_character_relation_metrics
)
_compute_language_style_metrics = _deprecated_alias(
    "_compute_language_style_metrics", compute_language_style_metrics
)
_compute_traditional_culture_metrics = _deprecated_alias(
    "_compute_traditional_culture_metrics", compute_traditional_culture_metrics
)
_map_emotion_score = _deprecated_alias("_map_emotion_score", map_emotion_score)

__all__ = [
    "AggregateResult",
    "AnnotationData",
    "CharacterData",
    "CultureData",
    "EmotionData",
    "RelationData",
    "TensionData",
    "TextData",
    "fetch_annotation_data",
    "fetch_emotion_data",
    "fetch_character_data",
    "fetch_relation_data",
    "fetch_text_data",
    "fetch_culture_data",
    "fetch_tension_data",
    "compute_narrative_structure_metrics",
    "compute_emotion_curve_metrics",
    "compute_character_relation_metrics",
    "compute_language_style_metrics",
    "compute_traditional_culture_metrics",
    "map_emotion_score",
    "_fetch_annotation_data",
    "_fetch_emotion_data",
    "_fetch_character_data",
    "_fetch_relation_data",
    "_fetch_text_data",
    "_fetch_culture_data",
    "_fetch_tension_data",
    "_compute_narrative_structure_metrics",
    "_compute_emotion_curve_metrics",
    "_compute_character_relation_metrics",
    "_compute_language_style_metrics",
    "_compute_traditional_culture_metrics",
    "_map_emotion_score",
]


def aggregate_all_metrics(
    run_id: str,
    annotation_repo,
    chunk_repo,
    stats_repo,
) -> AggregateResult:
    """Aggregate all metric groups into a single result object."""
    result = AggregateResult()

    annotation_data = fetch_annotation_data(annotation_repo, run_id)
    emotion_data = fetch_emotion_data(stats_repo, run_id)
    char_data = fetch_character_data(annotation_repo, run_id)
    relation_data = fetch_relation_data(annotation_repo, run_id)
    text_data = fetch_text_data(chunk_repo, run_id)
    culture_data = fetch_culture_data(stats_repo, run_id)
    tension_data = fetch_tension_data(stats_repo, run_id)

    total_chunks = chunk_repo.count_chunks(run_id) or 1

    result.narrative_structure = compute_narrative_structure_metrics(annotation_data, tension_data)
    result.emotion_curve = compute_emotion_curve_metrics(emotion_data, annotation_data, char_data)
    result.character_relations = compute_character_relation_metrics(relation_data, char_data, total_chunks)
    result.language_style = compute_language_style_metrics(text_data, annotation_data.emotional_valences)
    result.traditional_culture = compute_traditional_culture_metrics(culture_data, text_data.texts)

    return result
