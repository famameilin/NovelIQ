from __future__ import annotations

from typing import Final
from typing import Any

from src.api.models.responses import (
    CharacterStatsAggregate,
    CultureStats,
    EmotionStats,
    NarrativeStructureStats,
    StyleStats,
)
from src.metrics.aggregate import AggregateResult

AGGREGATE_METRIC_CONTRACT_FIELDS: Final[tuple[str, ...]] = (
    "narrative_structure",
    "emotion_stats",
    "character_stats",
    "style_stats",
    "culture_stats",
)
AGGREGATE_GRAPH_FORBIDDEN_FIELDS: Final[frozenset[str]] = frozenset({"graph_summary", "graph_quality_report"})


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
    """转换叙事结构统计数据。

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-api-layer-functions
    说明: 从 _convert_aggregate_result 拆分出来，专门处理叙事结构统计转换。
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
        climax_count=result.narrative_structure.get("climax_count"),
        climax_positions=result.narrative_structure.get("climax_positions"),
        climax_heights=result.narrative_structure.get("climax_heights"),
        peak_escalation=result.narrative_structure.get("peak_escalation"),
        dominant_climax_pos=result.narrative_structure.get("dominant_climax_pos"),
    )


def _convert_emotion_stats(
    result: AggregateResult,
) -> EmotionStats | None:
    """转换情感统计数据。

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-api-layer-functions
    说明: 从 _convert_aggregate_result 拆分出来，专门处理情感统计转换。
    """
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
    """转换人物统计数据。

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-api-layer-functions
    说明: 从 _convert_aggregate_result 拆分出来，专门处理人物统计转换。
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
) -> StyleStats | None:
    """转换风格统计数据。

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-api-layer-functions
    说明: 从 _convert_aggregate_result 拆分出来，专门处理风格统计转换。

    修改时间: 2026-04-04
    修改者: TraeAI
    任务: fix-style-stats-missing-fields
    修改内容: 添加 dialogue_ratio 和 avg_sent_len 字段转换。
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
    """转换文化统计数据。

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-api-layer-functions
    说明: 从 _convert_aggregate_result 拆分出来，专门处理文化统计转换。

    修改时间: 2026-04-04
    修改者: TraeAI
    任务: merge-culture-to-style-add-topics
    修改内容: 不再返回文化指标（成语密度、古典句式比例、意象密度），因为价值有限。
              保留函数和模型定义，避免破坏性变更。
    """
    return None


def _convert_aggregate_result(
    result: AggregateResult,
) -> tuple[
    NarrativeStructureStats | None,
    EmotionStats | None,
    CharacterStatsAggregate | None,
    StyleStats | None,
    CultureStats | None,
]:
    """转换聚合结果为响应模型。

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-api-layer-functions
    说明: 将原有逻辑拆分为 5 个独立的转换函数，提高代码可读性和可维护性。
    """
    narrative_structure = _convert_narrative_structure(result)
    emotion_stats = _convert_emotion_stats(result)
    character_stats = _convert_character_stats(result)
    style_stats = _convert_style_stats(result)
    culture_stats = _convert_culture_stats(result)

    return narrative_structure, emotion_stats, character_stats, style_stats, culture_stats


def validate_aggregate_metrics_contract(aggregate_metrics: dict[str, Any]) -> None:
    """
    验证 aggregate 导出 contract。

    中文注释：aggregate_metrics 是非 graph 的最终结构化结论出口，必须固定
    为五组 aggregate 指标，不能混入 graph signals，也不能被 diagnosis/page
    字段反向污染。
    """

    keys = set(aggregate_metrics.keys())
    forbidden = sorted(keys & AGGREGATE_GRAPH_FORBIDDEN_FIELDS)
    if forbidden:
        raise ValueError(
            "aggregate_metrics must not include graph-owned fields: "
            + ", ".join(forbidden)
        )

    expected = set(AGGREGATE_METRIC_CONTRACT_FIELDS)
    missing = sorted(expected - keys)
    unexpected = sorted(keys - expected)
    if missing or unexpected:
        detail_parts: list[str] = []
        if missing:
            detail_parts.append("missing=" + ", ".join(missing))
        if unexpected:
            detail_parts.append("unexpected=" + ", ".join(unexpected))
        raise ValueError("aggregate_metrics contract mismatch: " + "; ".join(detail_parts))


def build_aggregate_metrics_contract(result: AggregateResult) -> dict[str, Any]:
    """Build the stable non-graph aggregate metrics bundle used by export surfaces."""

    narrative_structure, emotion_stats, character_stats, style_stats, culture_stats = _convert_aggregate_result(result)
    aggregate_metrics = {
        "narrative_structure": narrative_structure.model_dump() if narrative_structure else None,
        "emotion_stats": emotion_stats.model_dump() if emotion_stats else None,
        "character_stats": character_stats.model_dump() if character_stats else None,
        "style_stats": style_stats.model_dump() if style_stats else None,
        "culture_stats": culture_stats.model_dump() if culture_stats else None,
    }
    validate_aggregate_metrics_contract(aggregate_metrics)
    return aggregate_metrics
