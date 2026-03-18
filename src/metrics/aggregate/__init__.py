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
    fetch_emotion_data,
    fetch_relation_data,
    fetch_tension_data,
    fetch_text_data,
)
from .types import (
    AggregateResult,
    AnnotationData,
    CharacterData,
    CultureData,
    EmotionData,
    RelationData,
    TensionData,
    TextData,
)

__all__ = [
    # types
    "AggregateResult",
    "AnnotationData",
    "CharacterData",
    "CultureData",
    "EmotionData",
    "RelationData",
    "TensionData",
    "TextData",
    # fetchers
    "fetch_annotation_data",
    "fetch_emotion_data",
    "fetch_character_data",
    "fetch_relation_data",
    "fetch_text_data",
    "fetch_culture_data",
    "fetch_tension_data",
    # computers
    "compute_narrative_structure_metrics",
    "compute_emotion_curve_metrics",
    "compute_character_relation_metrics",
    "compute_language_style_metrics",
    "compute_traditional_culture_metrics",
]
