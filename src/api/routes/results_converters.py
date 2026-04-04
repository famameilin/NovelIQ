from __future__ import annotations

from typing import Any

from src.api.models.responses import (
    CharacterStatsAggregate,
    CultureStats,
    EmotionStats,
    NarrativeStructureStats,
    StyleStats,
)
from src.metrics.aggregate import AggregateResult


def _default_distribution(value: Any) -> dict[str, float]:
    return value if isinstance(value, dict) else {}


def _default_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _convert_narrative_structure(
    result: AggregateResult,
) -> NarrativeStructureStats | None:
    """
    杞崲鍙欎簨缁撴瀯缁熻鏁版嵁銆?
    鍒涘缓鏃堕棿: 2026-03-13
    鍒涘缓鑰? TraeAI
    浠诲姟: refactor-api-layer-functions
    浠?_convert_aggregate_result 鎷嗗垎鍑烘潵锛屼笓闂ㄥ鐞嗗彊浜嬬粨鏋勭粺璁¤浆鎹€?"""
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
        climax_count=result.narrative_structure.get("climax_count"),
        climax_positions=result.narrative_structure.get("climax_positions"),
        climax_heights=result.narrative_structure.get("climax_heights"),
        peak_escalation=result.narrative_structure.get("peak_escalation"),
        dominant_climax_pos=result.narrative_structure.get("dominant_climax_pos"),
    )


def _convert_emotion_stats(
    result: AggregateResult,
) -> EmotionStats | None:
    """
    杞崲鎯呮劅缁熻鏁版嵁銆?
    鍒涘缓鏃堕棿: 2026-03-13
    鍒涘缓鑰? TraeAI
    浠诲姟: refactor-api-layer-functions
    浠?_convert_aggregate_result 鎷嗗垎鍑烘潵锛屼笓闂ㄥ鐞嗘儏鎰熺粺璁¤浆鎹€?"""
    if not result.emotion_curve:
        return None

    curve_type = result.emotion_curve.get("lexical_emotion_trend")

    return EmotionStats(
        pos_neg_ratio=result.emotion_curve.get("pos_neg_ratio"),
        positive_ratio=result.emotion_curve.get("positive_ratio"),
        negative_ratio=result.emotion_curve.get("negative_ratio"),
        neutral_ratio=result.emotion_curve.get("neutral_ratio"),
        recovery_speed=result.emotion_curve.get("emotion_recovery_speed"),
        pivot_moment_density=result.emotion_curve.get("pivot_moment_density"),
        lexical_emotion_trend=str(curve_type) if curve_type is not None else None,
    )


def _convert_character_stats(
    result: AggregateResult,
) -> CharacterStatsAggregate | None:
    """
    杞崲浜虹墿缁熻鏁版嵁銆?
    鍒涘缓鏃堕棿: 2026-03-13
    鍒涘缓鑰? TraeAI
    浠诲姟: refactor-api-layer-functions
    浠?_convert_aggregate_result 鎷嗗垎鍑烘潵锛屼笓闂ㄥ鐞嗕汉鐗╃粺璁¤浆鎹€?"""
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
) -> StyleStats | None:
    """
    杞崲椋庢牸缁熻鏁版嵁銆?
    鍒涘缓鏃堕棿: 2026-03-13
    鍒涘缓鑰? TraeAI
    浠诲姟: refactor-api-layer-functions
    浠?_convert_aggregate_result 鎷嗗垎鍑烘潵锛屼笓闂ㄥ鐞嗛鏍肩粺璁¤浆鎹€?"""
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
        tone_distribution=_default_distribution(lang_dict.get("tone_distribution")),
        vocab_breadth=lang_dict.get("vocab_breadth"),
        avg_word_len=lang_dict.get("avg_word_len"),
        sent_len_std=lang_dict.get("sent_len_std"),
        dialogue_ratio=lang_dict.get("dialogue_ratio"),
        avg_sent_len=lang_dict.get("avg_sent_len"),
        function_word_vector=function_word_vector,
        category_density=category_density,
    )


def _convert_culture_stats(
    result: AggregateResult,
) -> CultureStats | None:
    """
    杞崲鏂囧寲缁熻鏁版嵁銆?
    鍒涘缓鏃堕棿: 2026-03-13
    鍒涘缓鑰? TraeAI
    浠诲姟: refactor-api-layer-functions
    浠?_convert_aggregate_result 鎷嗗垎鍑烘潵锛屼笓闂ㄥ鐞嗘枃鍖栫粺璁¤浆鎹€?"""
    if not result.traditional_culture:
        return None

    return CultureStats(
        idiom_density=result.traditional_culture.get("idiom_density"),
        classical_sentence_ratio=result.traditional_culture.get("classical_sentence_ratio"),
        imagery_density=_default_float(result.traditional_culture.get("imagery_density")),
    )


def _convert_aggregate_result(
    result: AggregateResult,
) -> tuple[
    NarrativeStructureStats | None,
    EmotionStats | None,
    CharacterStatsAggregate | None,
    StyleStats | None,
    CultureStats | None,
]:
    """
    杞崲鑱氬悎缁撴灉涓哄搷搴旀ā鍨嬨€?
    淇敼鏃堕棿: 2026-03-13
    淇敼鑰? TraeAI
    浠诲姟: refactor-api-layer-functions
    閲嶆瀯璇存槑: 灏嗗師鏈夐€昏緫鎷嗗垎涓?涓嫭绔嬬殑杞崲鍑芥暟锛屾彁楂樹唬鐮佸彲璇绘€у拰鍙淮鎶ゆ€с€?"""
    narrative_structure = _convert_narrative_structure(result)
    emotion_stats = _convert_emotion_stats(result)
    character_stats = _convert_character_stats(result)
    style_stats = _convert_style_stats(result)
    culture_stats = _convert_culture_stats(result)

    return narrative_structure, emotion_stats, character_stats, style_stats, culture_stats
