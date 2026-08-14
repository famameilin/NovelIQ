"""
Aggregate Metrics 数据类型定义

提取所有数据类定义
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.config.constants import EMOTION_SCORE_MAPPING


@dataclass
class AggregateResult:
    """聚合结果数据类

    """

    narrative_structure: dict[str, Any] = field(default_factory=dict)
    emotion_curve: dict[str, Any] = field(default_factory=dict)
    character_relations: dict[str, Any] = field(default_factory=dict)
    language_style: dict[str, Any] = field(default_factory=dict)
    traditional_culture: dict[str, float | None] = field(default_factory=dict)


@dataclass
class AnnotationData:
    """标注数据"""

    chunk_ids: list[int]
    event_types: list[str]
    cliffhangers: list[int]
    pivot_moments: list[int]
    emotional_valences: list[str]


@dataclass
class EmotionData:
    """情感数据"""

    emotion_values: list[float]
    pos_densities: list[float]
    neg_densities: list[float]


@dataclass
class CharacterData:
    """人物数据"""

    characters: list[tuple[str, str, int]]
    char_emotion_scores: list[tuple[str, list[float]]]


@dataclass
class RelationData:
    """关系数据"""

    relations: list[tuple[str, str]]
    full_relations: list[tuple[str, str, str, str]]
    participant_names: list[str] = field(default_factory=list)


@dataclass
class TextData:
    """文本数据"""

    texts: list[str]
    all_tokens: list[str]


@dataclass
class CultureData:
    """文化数据

    """

    imagery_densities: list[float]


@dataclass
class TensionData:
    """张力数据"""

    chunk_ids: list[int]
    tension_composite_scores: list[float | None]


@dataclass
class DialogueData:
    """对话数据

    存储对话语气数据用于聚合计算
    """

    tones: list[str]


@dataclass
class StyleData:
    """风格指标数据（全书守恒聚合，§9.1）

    2026-08-14 M8b：由每章比值列表改为全书分子/分母守恒值——
    dialogue_ratio = Σdialogue_char_count / Σchar_count，
    avg_sent_len = Σsentence_char_sum / Σsentence_count。
    """

    dialogue_ratio: float | None
    avg_sent_len: float | None


def map_emotion_score(score_raw: str | None) -> int:
    """
    将情绪分数字符串映射为数值

    """
    if score_raw in EMOTION_SCORE_MAPPING:
        return EMOTION_SCORE_MAPPING[score_raw]
    return 0
