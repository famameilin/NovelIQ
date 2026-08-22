"""
Aggregate Metrics 指标计算模块

提取所有指标计算函数

"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from src.config import settings

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
    compute_function_word_vector,
    compute_sent_len_std,
    compute_string_token_diversity,
)
from .types import (
    AnnotationData,
    CharacterData,
    EmotionData,
    RelationData,
    StyleData,
    TensionData,
    TextData,
)


@dataclass(slots=True)
class _AlignedNarrativeStructureInputs:
    """annotation ∩ tension 按 chapter_id 对齐，并附归一化进度轴。"""

    chapter_ids: list[int]
    event_types: list[str]
    cliffhangers: list[int]
    pivot_moments: list[int]
    tension_scores: list[float]
    positions: list[float]


def _align_narrative_structure_inputs(
    annotation_data: AnnotationData,
    tension_data: TensionData,
) -> _AlignedNarrativeStructureInputs:
    tension_by_chapter_id: dict[int, tuple[float, float]] = {}
    positions = tension_data.positions or [None] * len(tension_data.chapter_ids)
    for chapter_id, tension_score, position in zip(
        tension_data.chapter_ids,
        tension_data.tension_composite_scores,
        positions,
        strict=True,
    ):
        if tension_score is None or position is None or chapter_id in tension_by_chapter_id:
            continue
        tension_by_chapter_id[chapter_id] = (float(tension_score), float(position))

    aligned_chapter_ids: list[int] = []
    aligned_event_types: list[str] = []
    aligned_cliffhangers: list[int] = []
    aligned_pivot_moments: list[int] = []
    aligned_tension_scores: list[float] = []
    aligned_positions: list[float] = []

    for index, chapter_id in enumerate(annotation_data.chapter_ids):
        packed = tension_by_chapter_id.get(chapter_id)
        if packed is None:
            continue
        tension_score, position = packed
        aligned_chapter_ids.append(chapter_id)
        aligned_event_types.append(annotation_data.event_types[index])
        aligned_cliffhangers.append(annotation_data.cliffhangers[index])
        aligned_pivot_moments.append(annotation_data.pivot_moments[index])
        aligned_tension_scores.append(tension_score)
        aligned_positions.append(position)

    return _AlignedNarrativeStructureInputs(
        chapter_ids=aligned_chapter_ids,
        event_types=aligned_event_types,
        cliffhangers=aligned_cliffhangers,
        pivot_moments=aligned_pivot_moments,
        tension_scores=aligned_tension_scores,
        positions=aligned_positions,
    )


def _positions_are_usable(positions: list[float]) -> bool:
    if len(positions) < 2:
        return False
    for prev, curr in zip(positions[:-1], positions[1:], strict=True):
        if curr <= prev:
            return False
    return True


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


def _null_narrative_structure(event_types: list[str]) -> dict[str, Any]:
    return {
        "act1_ratio": None,
        "act2_ratio": None,
        "act3_ratio": None,
        "climax_spacing": None,
        "middle_collapse_index": None,
        "cliffhanger_rate": None,
        **{f"chapter_narrative_function_share_{k}": v for k, v in compute_event_density(event_types).items()},
        "climax_count": 0,
        "climax_positions": [],
        "climax_heights": [],
        "peak_escalation": None,
        "dominant_climax_pos": None,
    }


def compute_narrative_structure_metrics(
    annotation_data: AnnotationData,
    tension_data: TensionData,
) -> dict[str, Any]:
    """叙事结构聚合：归一化字符进度轴；小样本/无进度 → null。"""
    aligned_inputs = _align_narrative_structure_inputs(annotation_data, tension_data)
    small_sample = len(aligned_inputs.chapter_ids) < settings.metrics.small_sample_min_chapters
    if small_sample or not _positions_are_usable(aligned_inputs.positions):
        # 叙事功能占比分母为全部有效标注章节，不随张力交集收缩（契约：分母=有效标注章数）
        return _null_narrative_structure(annotation_data.event_types)

    diagnostics = analyze_three_act_structure(
        aligned_inputs.positions,
        aligned_inputs.event_types,
        aligned_inputs.cliffhangers,
        aligned_inputs.pivot_moments,
        aligned_inputs.tension_scores,
    )
    climax_profile = compute_climax_profile(aligned_inputs.positions, aligned_inputs.tension_scores)
    peak_idx = diagnostics.representative_peak_idx
    dominant_climax_pos = None
    if 0 <= peak_idx < len(aligned_inputs.positions):
        dominant_climax_pos = round(aligned_inputs.positions[peak_idx], 3)
    return {
        **diagnostics.ratio_dict(),
        "climax_spacing": compute_climax_spacing(aligned_inputs.positions, aligned_inputs.tension_scores),
        "middle_collapse_index": compute_middle_collapse_index(
            aligned_inputs.positions,
            aligned_inputs.tension_scores,
        ),
        "cliffhanger_rate": compute_cliffhanger_rate(aligned_inputs.cliffhangers),
        **{
            f"chapter_narrative_function_share_{k}": v
            for k, v in compute_event_density(annotation_data.event_types).items()
        },
        "climax_count": climax_profile["climax_count"],
        "climax_positions": climax_profile["climax_positions"],
        "climax_heights": climax_profile["climax_heights"],
        "peak_escalation": climax_profile["peak_escalation"],
        "dominant_climax_pos": (
            dominant_climax_pos if dominant_climax_pos is not None else climax_profile.get("dominant_climax_pos")
        ),
    }


def compute_emotion_curve_metrics(
    emotion_data: EmotionData,
    annotation_data: AnnotationData,
    char_data: CharacterData,
) -> dict[str, Any]:
    """情感曲线聚合：恢复速度/词表趋势走进度轴。"""
    positions = emotion_data.positions
    values = emotion_data.emotion_values
    can_use_progress = len(positions) == len(values) and len(values) >= 2 and _positions_are_usable(list(positions))
    return {
        "emotion_recovery_speed": (compute_emotion_recovery_speed(positions, values) if can_use_progress else None),
        "chapter_pivot_rate": (
            compute_pivot_moment_density(annotation_data.pivot_moments)
            if len(annotation_data.chapter_ids) >= settings.metrics.small_sample_min_chapters
            else None
        ),
        **compute_emotion_polarity_distribution(annotation_data.emotional_valences),
        "lexical_pos_neg_ratio": compute_pos_neg_ratio(emotion_data.pos_densities, emotion_data.neg_densities),
        "arc_delta": compute_arc_delta(char_data.char_emotion_scores),
        "lexical_emotion_trend": (compute_lexical_emotion_trend(positions, values) if can_use_progress else None),
    }


# 人物聚合的 network_density 与 graph page 使用同一批参与者
def compute_character_relation_metrics(
    relation_data: RelationData,
    char_data: CharacterData,
    total_chars: int,
) -> dict[str, Any]:
    """计算人物关系聚合指标（total_chars 为全书总字符数，用于每万字关系变化频率，§19.10）"""
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
        **compute_relation_change_frequency(relation_data.full_relations, total_chars),
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
    result: dict[str, Any] = {
        "tone_distribution": _compute_tone_distribution(dialogue_tones),
        "string_token_diversity": compute_string_token_diversity(text_data.all_tokens),
        "avg_word_len": compute_avg_word_len(text_data.texts),
        "sent_len_std": compute_sent_len_std(text_data.texts),
        **{f"category_density_{k}": v for k, v in compute_category_density(text_data.texts).items()},
    }
    function_word_vector = compute_function_word_vector(text_data.texts)
    if function_word_vector is not None:
        result.update({f"function_word_{k}": v for k, v in function_word_vector.items()})

    if style_data:
        # §9.1 守恒：全书比率 = 分子之和 / 分母之和，禁止对章节比值等权平均
        result["dialogue_ratio"] = style_data.dialogue_ratio
        result["avg_sent_len"] = style_data.avg_sent_len
    else:
        result["dialogue_ratio"] = None
        result["avg_sent_len"] = None

    return result
