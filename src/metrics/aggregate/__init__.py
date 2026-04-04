"""
Aggregate Metrics 模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 11 拆分aggregate_metrics.py
说明: 指标聚合功能模块
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
    chunk_repo,
    stats_repo,
) -> AggregateResult:
    """
    Aggregate all metric groups into a single result object.

    修改时间: 2026-04-04
    修改者: TraeAI
    任务: fix-style-stats-missing-fields
    修改内容: 添加 fetch_style_data 调用，传递 style_data 给 compute_language_style_metrics
    """
    result = AggregateResult()

    annotation_data = fetch_annotation_data(annotation_repo, run_id)
    emotion_data = fetch_emotion_data(stats_repo, run_id)
    char_data = fetch_character_data(annotation_repo, run_id)
    relation_data = fetch_relation_data(annotation_repo, run_id)
    text_data = fetch_text_data(chunk_repo, run_id)
    culture_data = fetch_culture_data(stats_repo, run_id)
    tension_data = fetch_tension_data(stats_repo, run_id)
    dialogue_data = fetch_dialogue_data(annotation_repo, run_id)
    style_data = fetch_style_data(chunk_repo, run_id)

    total_chunks = chunk_repo.count_chunks(run_id) or 1

    result.narrative_structure = compute_narrative_structure_metrics(annotation_data, tension_data)
    result.emotion_curve = compute_emotion_curve_metrics(emotion_data, annotation_data, char_data)
    result.character_relations = compute_character_relation_metrics(relation_data, char_data, total_chunks)
    result.language_style = compute_language_style_metrics(text_data, dialogue_data.tones, style_data)
    result.traditional_culture = compute_traditional_culture_metrics(culture_data, text_data.texts)

    return result


__all__ = [
    # types
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
    # fetchers
    "fetch_annotation_data",
    "fetch_emotion_data",
    "fetch_character_data",
    "fetch_relation_data",
    "fetch_text_data",
    "fetch_culture_data",
    "fetch_tension_data",
    "fetch_dialogue_data",
    "fetch_style_data",
    # computers
    "compute_narrative_structure_metrics",
    "compute_emotion_curve_metrics",
    "compute_character_relation_metrics",
    "compute_language_style_metrics",
    "compute_traditional_culture_metrics",
]
