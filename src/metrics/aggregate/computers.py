"""
Aggregate Metrics 指标计算模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 11 拆分aggregate_metrics.py
说明: 提取所有指标计算函数
"""

from __future__ import annotations

import statistics
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


def compute_narrative_structure_metrics(
    annotation_data: AnnotationData,
    tension_data: TensionData,
) -> Dict[str, Any]:
    """
    计算叙事结构聚合指标

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-metrics-layer-functions

    修改时间: 2026-03-13
    修改者: TraeAI
    任务: chunk-annotation-schema-refactor
    修改内容: 使用 tension_composite 计算三幕比例、高潮定位、中间塌陷指数

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 11 拆分aggregate_metrics.py
    修改内容: 提取为独立模块函数
    """
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
    """
    计算情感曲线聚合指标

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-metrics-layer-functions

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 11 拆分aggregate_metrics.py
    修改内容: 提取为独立模块函数
    """
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
    """
    计算人物关系聚合指标

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-metrics-layer-functions

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 11 拆分aggregate_metrics.py
    修改内容: 提取为独立模块函数
    """
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


def compute_language_style_metrics(text_data: TextData) -> Dict[str, Any]:
    """
    计算语言风格聚合指标

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-metrics-layer-functions

    修改时间: 2026-03-13
    修改者: TraeAI
    任务: chunk-annotation-schema-refactor
    修改内容: 删除 tone_distribution 计算（tone 字段已移除）

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 11 拆分aggregate_metrics.py
    修改内容: 提取为独立模块函数
    """
    return {
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
    """
    计算传统文化聚合指标

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-metrics-layer-functions

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 11 拆分aggregate_metrics.py
    修改内容: 提取为独立模块函数
    """
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
