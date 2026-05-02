"""
Aggregate Metrics 指标计算模块

提取所有指标计算函数

"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..character_metrics import (
    build_character_graph,
    compute_antagonist_strength_gap,
    compute_average_clustering,
    compute_character_degree_centrality,
    compute_character_function_coverage,
    compute_greimas_coverage,
    compute_largest_component_size,
    compute_number_of_connected_components,
    compute_relation_change_frequency,
    compute_relation_network_density,
)
from ..emotion_metrics_extra import (
    compute_arc_delta,
    compute_emotion_polarity_distribution,
    compute_emotion_recovery_speed,
    compute_lexical_emotion_trend,
    compute_pivot_moment_density,
    compute_pos_neg_ratio,
)
from ..narrative_metrics import (
    analyze_three_act_structure,
    compute_cliffhanger_rate,
    compute_climax_profile,
    compute_climax_spacing,
    compute_event_density,
    compute_middle_collapse_index,
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
    StyleData,
    TensionData,
    TextData,
)


@dataclass(slots=True)
class _AlignedNarrativeStructureInputs:
    """
    创建时间: 2026-05-02
    任务: three-act-structure-v2-cleanup
    新建原因: 三幕结构 v2 需要把 annotation 与 tension 按 chunk_id 对齐，
              不能继续默认两条序列在过滤空值后仍然天然同位。
    """

    chunk_ids: list[int]
    event_types: list[str]
    cliffhangers: list[int]
    pivot_moments: list[int]
    tension_scores: list[float]


def _align_narrative_structure_inputs(
    annotation_data: AnnotationData,
    tension_data: TensionData,
) -> _AlignedNarrativeStructureInputs:
    tension_by_chunk_id: dict[int, float] = {}
    for chunk_id, tension_score in zip(
        tension_data.chunk_ids,
        tension_data.tension_composite_scores,
        strict=True,
    ):
        if tension_score is None or chunk_id in tension_by_chunk_id:
            continue
        tension_by_chunk_id[chunk_id] = float(tension_score)

    aligned_chunk_ids: list[int] = []
    aligned_event_types: list[str] = []
    aligned_cliffhangers: list[int] = []
    aligned_pivot_moments: list[int] = []
    aligned_tension_scores: list[float] = []

    for index, chunk_id in enumerate(annotation_data.chunk_ids):
        tension_score = tension_by_chunk_id.get(chunk_id)
        if tension_score is None:
            continue
        aligned_chunk_ids.append(chunk_id)
        aligned_event_types.append(annotation_data.event_types[index])
        aligned_cliffhangers.append(annotation_data.cliffhangers[index])
        aligned_pivot_moments.append(annotation_data.pivot_moments[index])
        aligned_tension_scores.append(tension_score)

    return _AlignedNarrativeStructureInputs(
        chunk_ids=aligned_chunk_ids,
        event_types=aligned_event_types,
        cliffhangers=aligned_cliffhangers,
        pivot_moments=aligned_pivot_moments,
        tension_scores=aligned_tension_scores,
    )


def _compute_tone_distribution(dialogue_tones: list[str] | None) -> dict[str, float]:
    """
    计算对话语气分布

    """
    if not dialogue_tones:
        return {}

    valid_tones = [t for t in dialogue_tones if t]
    if not valid_tones:
        return {}

    counts = Counter(valid_tones)
    total = sum(counts.values())
    if total == 0:
        return {}

    return {tone: count / total for tone, count in counts.items()}


def compute_narrative_structure_metrics(
    annotation_data: AnnotationData,
    tension_data: TensionData,
) -> dict[str, Any]:
    """
    计算叙事结构聚合指标

    """
    aligned_inputs = _align_narrative_structure_inputs(annotation_data, tension_data)
    diagnostics = analyze_three_act_structure(
        aligned_inputs.event_types,
        aligned_inputs.cliffhangers,
        aligned_inputs.pivot_moments,
        aligned_inputs.tension_scores,
    )
    climax_profile = compute_climax_profile(aligned_inputs.tension_scores)
    dominant_climax_pos = None
    if aligned_inputs.tension_scores:
        dominant_climax_pos = round(
            diagnostics.representative_peak_idx / len(aligned_inputs.tension_scores),
            3,
        )
    return {
        **diagnostics.ratio_dict(),
        "climax_spacing": compute_climax_spacing(aligned_inputs.chunk_ids, aligned_inputs.tension_scores),
        "middle_collapse_index": compute_middle_collapse_index(
            aligned_inputs.chunk_ids,
            aligned_inputs.tension_scores,
        ),
        "cliffhanger_rate": compute_cliffhanger_rate(aligned_inputs.cliffhangers),
        **{f"event_density_{k}": v for k, v in compute_event_density(aligned_inputs.event_types).items()},
        "climax_count": climax_profile["climax_count"],
        "climax_positions": climax_profile["climax_positions"],
        "climax_heights": climax_profile["climax_heights"],
        "peak_escalation": climax_profile["peak_escalation"],
        "dominant_climax_pos": dominant_climax_pos,
    }


def compute_emotion_curve_metrics(
    emotion_data: EmotionData,
    annotation_data: AnnotationData,
    char_data: CharacterData,
) -> dict[str, Any]:
    """
    计算情感曲线聚合指标

    """
    return {
        "emotion_recovery_speed": compute_emotion_recovery_speed(emotion_data.emotion_values),
        "pivot_moment_density": compute_pivot_moment_density(annotation_data.pivot_moments),
        **compute_emotion_polarity_distribution(annotation_data.emotional_valences),
        "pos_neg_ratio": compute_pos_neg_ratio(emotion_data.pos_densities, emotion_data.neg_densities),
        "arc_delta": compute_arc_delta(char_data.char_emotion_scores),
        "lexical_emotion_trend": compute_lexical_emotion_trend(emotion_data.emotion_values),
    }


# 2026-04-28，任务：统一关系图谱密度口径。
# 修改原因：人物聚合指标里的 `network_density` 需要和 graph page 共享同一批参与者，
# 避免孤点被排除后把密度抬高。
def compute_character_relation_metrics(
    relation_data: RelationData,
    char_data: CharacterData,
    total_chunks: int,
) -> dict[str, Any]:
    """计算人物关系聚合指标"""
    relation_input = relation_data.relations
    relation_graph = build_character_graph(relation_input) if relation_input else None
    result: dict[str, Any] = {
        "network_density": compute_relation_network_density(
            relation_input,
            node_names=relation_data.participant_names,
        ),
        "antagonist_strength_gap": compute_antagonist_strength_gap(char_data.characters),
        "average_clustering": compute_average_clustering(relation_input, graph=relation_graph),
        "num_connected_components": float(compute_number_of_connected_components(relation_input, graph=relation_graph)),
        "largest_component_size": float(compute_largest_component_size(relation_input, graph=relation_graph)),
        **compute_relation_change_frequency(relation_data.full_relations, total_chunks),
    }

    degree_centrality = compute_character_degree_centrality(relation_input, graph=relation_graph)
    if degree_centrality:
        max_char = max(degree_centrality, key=lambda k: degree_centrality[k] or 0.0)
        result["max_degree_character"] = max_char
        result["max_degree_value"] = degree_centrality[max_char] or 0.0
        result["degree_centrality"] = degree_centrality

    role_functions = [role_function for _name, role_function, _score in char_data.characters if role_function]
    result.update({f"function_coverage_{k}": v for k, v in compute_character_function_coverage(role_functions).items()})
    result["greimas_coverage"] = compute_greimas_coverage(role_functions)

    return result


def compute_language_style_metrics(
    text_data: TextData,
    dialogue_tones: list[str] | None = None,
    style_data: StyleData | None = None,
) -> dict[str, Any]:
    """
    计算语言风格聚合指标


    """
    result = {
        "tone_distribution": _compute_tone_distribution(dialogue_tones),
        "vocab_breadth": compute_vocab_breadth(text_data.all_tokens),
        "avg_word_len": compute_avg_word_len(text_data.texts),
        "sent_len_std": compute_sent_len_std(text_data.texts),
        **{f"function_word_{k}": v for k, v in compute_function_word_vector(text_data.texts).items()},
        **{f"category_density_{k}": v for k, v in compute_category_density(text_data.texts).items()},
    }

    if style_data:
        result["dialogue_ratio"] = float(np.mean(style_data.dialogue_ratios)) if style_data.dialogue_ratios else None
        result["avg_sent_len"] = float(np.mean(style_data.avg_sent_lens)) if style_data.avg_sent_lens else None
    else:
        result["dialogue_ratio"] = None
        result["avg_sent_len"] = None

    return result


def compute_traditional_culture_metrics(
    culture_data: CultureData,
    texts: list[str],
) -> dict[str, float | None]:
    """
    计算传统文化聚合指标

    """
    return {
        "idiom_density": compute_idiom_density(texts),
        "classical_sentence_ratio": compute_classical_sentence_ratio(texts),
        "imagery_density": compute_imagery_density(texts),
    }
