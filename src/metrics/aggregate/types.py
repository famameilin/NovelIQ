"""
Aggregate Metrics 数据类型定义

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 11 拆分aggregate_metrics.py
说明: 提取所有数据类定义
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.config.constants import EMOTION_SCORE_MAPPING


@dataclass
class AggregateResult:
    """聚合结果数据类

    修改时间: 2026-03-28
    修改者: TraeAI
    任务: fix/three-act-ratio-boundary-protection
    修改内容: narrative_structure 类型从 dict[str, float] 改为 dict[str, Any]，
              以支持多高潮剖面指标（climax_count: int, climax_positions: list, etc.）
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
    protagonist_name: str | None


@dataclass
class RelationData:
    """关系数据"""

    relations: list[tuple[str, str]]
    full_relations: list[tuple[str, str, str, str]]



@dataclass
class TextData:
    """文本数据"""

    texts: list[str]
    all_tokens: list[str]


@dataclass
class CultureData:
    """文化数据

    修改时间: 2026-03-26
    修改者: TraeAI
    任务: 简化文化指标系统
    修改内容: 删除低价值词表密度字段，只保留 imagery_densities
    """

    imagery_densities: list[float]


@dataclass
class TensionData:
    """张力数据"""

    tension_composite_scores: list[float]


@dataclass
class DialogueData:
    """对话数据

    创建时间: 2026-03-25
    创建者: TraeAI
    任务: fix-tone-distribution-semantic-error
    说明: 存储对话语气数据用于聚合计算
    """

    tones: list[str]


def map_emotion_score(score_raw: str | None) -> int:
    """
    将情绪分数字符串映射为数值

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: metrics-repository-refactor
    """
    if score_raw in EMOTION_SCORE_MAPPING:
        return EMOTION_SCORE_MAPPING[score_raw]
    return 0
