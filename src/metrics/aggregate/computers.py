"""
Aggregate Metrics 指标计算模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 11 拆分aggregate_metrics.py
说明: 提取所有指标计算函数

修改历史:
- 2026-03-13: 创建指标计算函数 (refactor-metrics-layer-functions)
- 2026-03-13: 使用 tension_composite 计算三幕比例 (chunk-annotation-schema-refactor)
- 2026-03-18: 提取为独立模块函数 (code-quality-refactor Task 11)

修改时间: 2026-03-25
修改者: TraeAI
任务: fix-tone-distribution-semantic-error
修改内容: 修正 _compute_tone_distribution 从 dialogue_tones 计算，移除 _TONE_LEGACY_MAPPING
"""

from __future__ import annotations

from collections import Counter
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
    compute_cliffhanger_rate,
    compute_climax_profile,
    compute_climax_spacing,
    compute_event_density,
    compute_middle_collapse_index,
    compute_three_act_ratio_by_tension,
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


def _compute_tone_distribution(dialogue_tones: list[str] | None) -> dict[str, float]:
    """
    计算对话语气分布

    修改时间: 2026-03-25
    修改者: TraeAI
    任务: fix-tone-distribution-semantic-error
    修改内容: 从 dialogue_tones 计算语气分布，而非 emotional_valences
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

    修改时间: 2026-03-28
    修改者: TraeAI
    任务: 叙事时间轴功能设计评估
    修改内容: 增加 compute_climax_profile 多高潮剖面指标
    """
    climax_profile = compute_climax_profile(tension_data.tension_composite_scores)
    return {
        **compute_three_act_ratio_by_tension(tension_data.tension_composite_scores),
        "climax_spacing": compute_climax_spacing(annotation_data.chunk_ids, tension_data.tension_composite_scores),
        "middle_collapse_index": compute_middle_collapse_index(
            annotation_data.chunk_ids, tension_data.tension_composite_scores
        ),
        "cliffhanger_rate": compute_cliffhanger_rate(annotation_data.cliffhangers),
        **{f"event_density_{k}": v for k, v in compute_event_density(annotation_data.event_types).items()},
        "climax_count": climax_profile["climax_count"],
        "climax_positions": climax_profile["climax_positions"],
        "climax_heights": climax_profile["climax_heights"],
        "peak_escalation": climax_profile["peak_escalation"],
        "dominant_climax_pos": climax_profile["dominant_climax_pos"],
    }


def compute_emotion_curve_metrics(
    emotion_data: EmotionData,
    annotation_data: AnnotationData,
    char_data: CharacterData,
) -> dict[str, Any]:
    """
    计算情感曲线聚合指标

    修改时间: 2026-03-25
    修改者: TraeAI
    任务: improve-emotion-curve-accuracy
    修改内容: 输出 lexical_emotion_trend 词表趋势指标
    """
    return {
        "emotion_recovery_speed": compute_emotion_recovery_speed(emotion_data.emotion_values),
        "pivot_moment_density": compute_pivot_moment_density(annotation_data.pivot_moments),
        **compute_emotion_polarity_distribution(annotation_data.emotional_valences),
        "pos_neg_ratio": compute_pos_neg_ratio(emotion_data.pos_densities, emotion_data.neg_densities),
        "arc_delta": compute_arc_delta(char_data.char_emotion_scores),
        "lexical_emotion_trend": compute_lexical_emotion_trend(emotion_data.emotion_values),
    }


def compute_character_relation_metrics(
    relation_data: RelationData,
    char_data: CharacterData,
    total_chunks: int,
) -> dict[str, Any]:
    """计算人物关系聚合指标"""
    relation_input = relation_data.relations
    relation_graph = build_character_graph(relation_input) if relation_input else None
    result: dict[str, Any] = {
        "network_density": compute_relation_network_density(relation_input, graph=relation_graph),
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

    修改时间: 2026-03-25
    修改者: TraeAI
    任务: fix-tone-distribution-semantic-error
    修改内容: 参数名从 emotional_valences 改为 dialogue_tones

    修改时间: 2026-04-04
    修改者: TraeAI
    任务: fix-style-stats-missing-fields
    修改内容: 添加 style_data 参数，计算 dialogue_ratio 和 avg_sent_len
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

    修改时间: 2026-03-26
    修改者: TraeAI
    任务: 简化文化指标系统
    修改内容: 删除低价值词表密度指标，只保留 idiom_density、classical_sentence_ratio、imagery_density
    """
    return {
        "idiom_density": compute_idiom_density(texts),
        "classical_sentence_ratio": compute_classical_sentence_ratio(texts),
        "imagery_density": compute_imagery_density(texts),
    }
