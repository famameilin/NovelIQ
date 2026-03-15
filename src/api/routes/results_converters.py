from __future__ import annotations

from typing import Optional, Tuple

from src.metrics.aggregate_metrics import AggregateResult
from src.api.models.responses import (
    NarrativeStructureStats,
    EmotionStats,
    CharacterStatsAggregate,
    StyleStats,
    CultureStats,
)


def _convert_narrative_structure(
    result: AggregateResult,
) -> Optional[NarrativeStructureStats]:
    """
    转换叙事结构统计数据。

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-api-layer-functions
    从 _convert_aggregate_result 拆分出来，专门处理叙事结构统计转换。
    """
    if not result.narrative_structure:
        return None

    event_density = {}
    for key, value in result.narrative_structure.items():
        if key.startswith("event_density_"):
            event_density[key.replace("event_density_", "")] = value

    return NarrativeStructureStats(
        act1_ratio=result.narrative_structure.get("act1_ratio"),
        act2_ratio=result.narrative_structure.get("act2_ratio"),
        act3_ratio=result.narrative_structure.get("act3_ratio"),
        climax_spacing=result.narrative_structure.get("climax_spacing"),
        middle_collapse_index=result.narrative_structure.get("middle_collapse_index"),
        event_density=event_density if event_density else None,
        cliffhanger_rate=result.narrative_structure.get("cliffhanger_rate"),
    )


def _convert_emotion_stats(
    result: AggregateResult,
) -> Optional[EmotionStats]:
    """
    转换情感统计数据。

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-api-layer-functions
    从 _convert_aggregate_result 拆分出来，专门处理情感统计转换。
    """
    if not result.emotion_curve:
        return None

    curve_type = result.emotion_curve.get("emotion_curve_type")

    return EmotionStats(
        pos_neg_ratio=result.emotion_curve.get("pos_neg_ratio"),
        positive_ratio=result.emotion_curve.get("positive_ratio"),
        negative_ratio=result.emotion_curve.get("negative_ratio"),
        neutral_ratio=result.emotion_curve.get("neutral_ratio"),
        recovery_speed=result.emotion_curve.get("emotion_recovery_speed"),
        pivot_moment_density=result.emotion_curve.get("pivot_moment_density"),
        emotion_curve_type=str(curve_type) if curve_type is not None else None,
    )


def _convert_character_stats(
    result: AggregateResult,
) -> Optional[CharacterStatsAggregate]:
    """
    转换人物统计数据。

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-api-layer-functions
    从 _convert_aggregate_result 拆分出来，专门处理人物统计转换。
    """
    if not result.character_relations:
        return None

    function_coverage_distribution: dict[str, float] = {}
    degree_centrality: dict[str, float] = {}
    greimas_coverage_value = None

    for key, value in result.character_relations.items():
        if key.startswith("function_coverage_"):
            function_coverage_distribution[key.replace("function_coverage_", "")] = value
        elif key == "greimas_coverage":
            greimas_coverage_value = value
        elif key in ["degree_centrality"] and isinstance(value, dict):
            degree_centrality = value

    return CharacterStatsAggregate(
        network_density=result.character_relations.get("network_density"),
        protagonist_betweenness=result.character_relations.get("protagonist_betweenness"),
        greimas_coverage=greimas_coverage_value,
        function_coverage_distribution=function_coverage_distribution if function_coverage_distribution else None,
        antagonist_strength_gap=result.character_relations.get("antagonist_strength_gap"),
        relation_change_freq=result.character_relations.get("change_rate"),
        degree_centrality=degree_centrality if degree_centrality else None,
    )


def _convert_style_stats(
    result: AggregateResult,
) -> Optional[StyleStats]:
    """
    转换风格统计数据。

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-api-layer-functions
    从 _convert_aggregate_result 拆分出来，专门处理风格统计转换。
    """
    if not result.language_style:
        return None

    lang_dict = result.language_style if isinstance(result.language_style, dict) else {}

    function_word_vector = None
    if lang_dict:
        function_word_vector = {
            k.replace("function_word_", ""): v for k, v in lang_dict.items() if k.startswith("function_word_")
        }
        if not function_word_vector:
            function_word_vector = None

    category_density = None
    if lang_dict:
        category_density = {
            k.replace("category_density_", ""): v for k, v in lang_dict.items() if k.startswith("category_density_")
        }
        if not category_density:
            category_density = None

    return StyleStats(
        tone_distribution=lang_dict.get("tone_distribution"),
        vocab_breadth=lang_dict.get("vocab_breadth"),
        avg_word_len=lang_dict.get("avg_word_len"),
        sent_len_std=lang_dict.get("sent_len_std"),
        function_word_vector=function_word_vector,
        category_density=category_density,
    )


def _convert_culture_stats(
    result: AggregateResult,
) -> Optional[CultureStats]:
    """
    转换文化统计数据。

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-api-layer-functions
    从 _convert_aggregate_result 拆分出来，专门处理文化统计转换。
    """
    if not result.traditional_culture:
        return None

    return CultureStats(
        confucian_density=result.traditional_culture.get("confucian_density"),
        taoist_density=result.traditional_culture.get("taoist_density"),
        buddhist_density=result.traditional_culture.get("buddhist_density"),
        folk_density=result.traditional_culture.get("folk_density"),
        allusion_density=result.traditional_culture.get("allusion_density"),
        idiom_density=result.traditional_culture.get("idiom_density"),
        classical_sentence_ratio=result.traditional_culture.get("classical_sentence_ratio"),
    )


def _convert_aggregate_result(
    result: AggregateResult,
) -> Tuple[
    Optional[NarrativeStructureStats],
    Optional[EmotionStats],
    Optional[CharacterStatsAggregate],
    Optional[StyleStats],
    Optional[CultureStats],
]:
    """
    转换聚合结果为响应模型。

    修改时间: 2026-03-13
    修改者: TraeAI
    任务: refactor-api-layer-functions
    重构说明: 将原有逻辑拆分为5个独立的转换函数，提高代码可读性和可维护性。
    """
    narrative_structure = _convert_narrative_structure(result)
    emotion_stats = _convert_emotion_stats(result)
    character_stats = _convert_character_stats(result)
    style_stats = _convert_style_stats(result)
    culture_stats = _convert_culture_stats(result)

    return narrative_structure, emotion_stats, character_stats, style_stats, culture_stats
