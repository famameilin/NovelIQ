"""
Aggregate Metrics 模块

指标聚合功能模块
"""

from __future__ import annotations

from .computers import (
    compute_character_relation_metrics,
    compute_emotion_curve_metrics,
    compute_language_style_metrics,
    compute_narrative_structure_metrics,
    compute_traditional_culture_metrics,
)
from .fetchers import (
    fetch_annotation_data,
    fetch_character_data,
    fetch_culture_data,
    fetch_dialogue_data,
    fetch_emotion_data,
    fetch_relation_data,
    fetch_style_data,
    fetch_tension_data,
    fetch_text_data,
)
from .types import (
    AggregateResult,
    AnnotationData,
    CharacterData,
    CultureData,
    DialogueData,
    EmotionData,
    RelationData,
    StyleData,
    TensionData,
    TextData,
    map_emotion_score,
)


def aggregate_all_metrics(
    run_id: str,
    annotation_repo,
    chapter_repo,
    stats_repo,
) -> AggregateResult:
    """
    把所有指标分组聚合成一个结果对象

    """
    result = AggregateResult()

    annotation_data = fetch_annotation_data(annotation_repo, run_id)
    emotion_data = fetch_emotion_data(stats_repo, run_id)
    char_data = fetch_character_data(annotation_repo, run_id)
    relation_data = fetch_relation_data(annotation_repo, run_id)
    text_data = fetch_text_data(chapter_repo, run_id)
    culture_data = fetch_culture_data(stats_repo, run_id)
    tension_data = fetch_tension_data(stats_repo, run_id)
    dialogue_data = fetch_dialogue_data(annotation_repo, run_id)
    style_data = fetch_style_data(chapter_repo, run_id)

    # 2026-08-14 修复（§19.10）：关系变化频率分母从章节数改为全书总字数。
    _, total_chars = chapter_repo.fetch_chapter_counts(run_id)

    result.narrative_structure = compute_narrative_structure_metrics(annotation_data, tension_data)
    result.emotion_curve = compute_emotion_curve_metrics(emotion_data, annotation_data, char_data)
    result.character_relations = compute_character_relation_metrics(relation_data, char_data, total_chars)
    result.language_style = compute_language_style_metrics(text_data, dialogue_data.tones, style_data)
    result.traditional_culture = compute_traditional_culture_metrics(culture_data, text_data.texts)

    return result


__all__ = [
    # 类型导出
    "AggregateResult",
    "AnnotationData",
    "CharacterData",
    "CultureData",
    "DialogueData",
    "EmotionData",
    "RelationData",
    "StyleData",
    "TensionData",
    "TextData",
    "map_emotion_score",
    "aggregate_all_metrics",
    # 数据提取
    "fetch_annotation_data",
    "fetch_emotion_data",
    "fetch_character_data",
    "fetch_relation_data",
    "fetch_text_data",
    "fetch_culture_data",
    "fetch_tension_data",
    "fetch_dialogue_data",
    "fetch_style_data",
    # 指标计算
    "compute_narrative_structure_metrics",
    "compute_emotion_curve_metrics",
    "compute_character_relation_metrics",
    "compute_language_style_metrics",
    "compute_traditional_culture_metrics",
]
