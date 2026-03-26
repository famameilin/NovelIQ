"""
Aggregate Metrics 数据类型定义

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 11 拆分aggregate_metrics.py
说明: 提取所有数据类定义
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple


@dataclass
class AggregateResult:
    """聚合结果数据类"""

    narrative_structure: Dict[str, float] = field(default_factory=dict)
    emotion_curve: Dict[str, Any] = field(default_factory=dict)
    character_relations: Dict[str, Any] = field(default_factory=dict)
    language_style: Dict[str, Any] = field(default_factory=dict)
    traditional_culture: Dict[str, float | None] = field(default_factory=dict)


@dataclass
class AnnotationData:
    """标注数据"""

    chunk_ids: List[int]
    event_types: List[str]
    cliffhangers: List[int]
    pivot_moments: List[int]
    emotional_valences: List[str]


@dataclass
class EmotionData:
    """情感数据"""

    emotion_values: List[float]
    pos_densities: List[float]
    neg_densities: List[float]


@dataclass
class CharacterData:
    """人物数据"""

    characters: List[Tuple[str, str, int]]
    char_emotion_scores: List[Tuple[str, List[float]]]
    protagonist_name: str | None


@dataclass
class RelationData:
    """关系数据"""

    relations: List[Tuple[str, str]]
    full_relations: List[Tuple[str, str, str, str]]


@dataclass
class TextData:
    """文本数据"""

    texts: List[str]
    all_tokens: List[str]


@dataclass
class CultureData:
    """文化数据

    修改时间: 2026-03-26
    修改者: TraeAI
    任务: 简化文化指标系统
    修改内容: 删除低价值词表密度字段，只保留 imagery_densities
    """

    imagery_densities: List[float]


@dataclass
class TensionData:
    """张力数据"""

    tension_composite_scores: List[float]


@dataclass
class DialogueData:
    """对话数据

    创建时间: 2026-03-25
    创建者: TraeAI
    任务: fix-tone-distribution-semantic-error
    说明: 存储对话语气数据用于聚合计算
    """

    tones: List[str]


# 情绪分数映射
EMOTION_SCORE_MAPPING = {
    "strong_positive": 2,
    "mild_positive": 1,
    "neutral": 0,
    "mild_negative": -1,
    "strong_negative": -2,
}


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
