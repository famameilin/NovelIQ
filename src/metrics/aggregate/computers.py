"""
Aggregate Metrics 鎸囨爣璁＄畻妯″潡

鍒涘缓鏃堕棿: 2026-03-18
鍒涘缓鑰? TraeAI
浠诲姟: code-quality-refactor - Task 11 鎷嗗垎aggregate_metrics.py
璇存槑: 鎻愬彇鎵€鏈夋寚鏍囪绠楀嚱鏁?

淇敼鍘嗗彶:
- 2026-03-13: 鍒涘缓鎸囨爣璁＄畻鍑芥暟 (refactor-metrics-layer-functions)
- 2026-03-13: 浣跨敤 tension_composite 璁＄畻涓夊箷姣斾緥 (chunk-annotation-schema-refactor)
- 2026-03-18: 鎻愬彇涓虹嫭绔嬫ā鍧楀嚱鏁?(code-quality-refactor Task 11)
"""

from __future__ import annotations

import statistics
from collections import Counter
from typing import Any, Dict

from ..narrative_metrics import (
    compute_cliffhanger_rate,
    compute_climax_spacing,
    compute_event_density,
    compute_middle_collapse_index,
    compute_three_act_ratio_by_tension,
)
from ..emotion_metrics_extra import (
    compute_arc_delta,
    compute_emotion_curve_type,
    compute_emotion_polarity_distribution,
    compute_emotion_recovery_speed,
    compute_pivot_moment_density,
    compute_pos_neg_ratio,
)
from ..character_metrics import (
    compute_antagonist_strength_gap,
    compute_average_clustering,
    compute_character_degree_centrality,
    compute_character_function_coverage,
    compute_greimas_coverage,
    compute_largest_component_size,
    compute_number_of_connected_components,
    compute_protagonist_betweenness,
    compute_relation_change_frequency,
    compute_relation_network_density,
)
from ..style_metrics_extra import (
    compute_avg_word_len,
    compute_category_density,
    compute_classical_sentence_ratio,
    compute_function_word_vector,
    compute_idiom_density,
    compute_imagery_density,
    compute_sent_len_std,
    compute_vocab_breadth,
)
from .types import (
    AnnotationData,
    CharacterData,
    CultureData,
    EmotionData,
    RelationData,
    TensionData,
    TextData,
)

_TONE_LEGACY_MAPPING = {
    "positive": "mild_positive",
    "negative": "mild_negative",
}


def _normalize_tone_label(label: str) -> str:
    normalized = label.strip().lower()
    return _TONE_LEGACY_MAPPING.get(normalized, normalized)


def _compute_tone_distribution(emotional_valences: list[str] | None) -> Dict[str, float]:
    if not emotional_valences:
        return {}

    normalized_labels = [_normalize_tone_label(value) for value in emotional_valences if value]
    if not normalized_labels:
        return {}

    counts = Counter(normalized_labels)
    total = sum(counts.values())
    if total == 0:
        return {}

    return {label: count / total for label, count in counts.items()}


def compute_narrative_structure_metrics(
    annotation_data: AnnotationData,
    tension_data: TensionData,
) -> Dict[str, Any]:
    """璁＄畻鍙欎簨缁撴瀯鑱氬悎鎸囨爣"""
    return {
        **compute_three_act_ratio_by_tension(tension_data.tension_composite_scores),
        "climax_spacing": compute_climax_spacing(annotation_data.chunk_ids, tension_data.tension_composite_scores),
        "middle_collapse_index": compute_middle_collapse_index(
            annotation_data.chunk_ids, tension_data.tension_composite_scores
        ),
        "cliffhanger_rate": compute_cliffhanger_rate(annotation_data.cliffhangers),
        **{f"event_density_{k}": v for k, v in compute_event_density(annotation_data.event_types).items()},
    }


def compute_emotion_curve_metrics(
    emotion_data: EmotionData,
    annotation_data: AnnotationData,
    char_data: CharacterData,
) -> Dict[str, Any]:
    """璁＄畻鎯呮劅鏇茬嚎鑱氬悎鎸囨爣"""
    return {
        "emotion_recovery_speed": compute_emotion_recovery_speed(emotion_data.emotion_values),
        "pivot_moment_density": compute_pivot_moment_density(annotation_data.pivot_moments),
        **compute_emotion_polarity_distribution(annotation_data.emotional_valences),
        "pos_neg_ratio": compute_pos_neg_ratio(emotion_data.pos_densities, emotion_data.neg_densities),
        "arc_delta": compute_arc_delta(char_data.char_emotion_scores),
        "emotion_curve_type": compute_emotion_curve_type(emotion_data.emotion_values),
    }


def compute_character_relation_metrics(
    relation_data: RelationData,
    char_data: CharacterData,
    total_chunks: int,
) -> Dict[str, Any]:
    """璁＄畻浜虹墿鍏崇郴鑱氬悎鎸囨爣"""
    result: Dict[str, Any] = {
        "network_density": compute_relation_network_density(relation_data.relations),
        "antagonist_strength_gap": compute_antagonist_strength_gap(char_data.characters),
        "average_clustering": compute_average_clustering(relation_data.relations),
        "num_connected_components": float(compute_number_of_connected_components(relation_data.relations)),
        "largest_component_size": float(compute_largest_component_size(relation_data.relations)),
        **compute_relation_change_frequency(relation_data.full_relations, total_chunks),
    }

    if char_data.protagonist_name:
        result["protagonist_betweenness"] = compute_protagonist_betweenness(
            relation_data.relations, char_data.protagonist_name
        )

    degree_centrality = compute_character_degree_centrality(relation_data.relations)
    if degree_centrality:
        max_char = max(degree_centrality, key=lambda k: degree_centrality[k] or 0.0)
        result["max_degree_character"] = max_char
        result["max_degree_value"] = degree_centrality[max_char] or 0.0
        result["degree_centrality"] = degree_centrality

    role_functions = [row[1] for row in char_data.characters if row[1]]
    result.update({f"function_coverage_{k}": v for k, v in compute_character_function_coverage(role_functions).items()})
    result["greimas_coverage"] = compute_greimas_coverage(role_functions)

    return result


def compute_language_style_metrics(
    text_data: TextData,
    emotional_valences: list[str] | None = None,
) -> Dict[str, Any]:
    """璁＄畻璇█椋庢牸鑱氬悎鎸囨爣"""
    return {
        "tone_distribution": _compute_tone_distribution(emotional_valences),
        "vocab_breadth": compute_vocab_breadth(text_data.all_tokens),
        "avg_word_len": compute_avg_word_len(text_data.texts),
        "sent_len_std": compute_sent_len_std(text_data.texts),
        **{f"function_word_{k}": v for k, v in compute_function_word_vector(text_data.texts).items()},
        **{f"category_density_{k}": v for k, v in compute_category_density(text_data.texts).items()},
    }


def compute_traditional_culture_metrics(
    culture_data: CultureData,
    texts: list[str],
) -> Dict[str, float | None]:
    """璁＄畻浼犵粺鏂囧寲鑱氬悎鎸囨爣"""
    return {
        "idiom_density": compute_idiom_density(texts),
        "classical_sentence_ratio": compute_classical_sentence_ratio(texts),
        "imagery_density": compute_imagery_density(texts),
        "confucian_density": statistics.mean(culture_data.confucian_densities)
        if culture_data.confucian_densities
        else None,
        "taoist_density": statistics.mean(culture_data.taoist_densities) if culture_data.taoist_densities else None,
        "buddhist_density": statistics.mean(culture_data.buddhist_densities)
        if culture_data.buddhist_densities
        else None,
        "folk_density": statistics.mean(culture_data.folk_densities) if culture_data.folk_densities else None,
        "allusion_density": statistics.mean(culture_data.allusion_densities)
        if culture_data.allusion_densities
        else None,
        "imagery_density_from_culture": statistics.mean(culture_data.imagery_densities)
        if culture_data.imagery_densities
        else None,
    }
