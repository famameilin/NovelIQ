"""
标注相关常量

说明: 从各模块提取的标注相关硬编码常量
"""

from __future__ import annotations

from typing import Literal

EMOTION_SCORE_MAPPING: dict[str, int] = {
    "strong_positive": 2,
    "mild_positive": 1,
    "neutral": 0,
    "mild_negative": -1,
    "strong_negative": -2,
}

VALID_ROLE_FUNCTIONS: tuple[str, ...] = ("主体", "客体", "发送者", "接收者", "帮助者", "反对者")
VALID_ACTION_TYPES: tuple[str, ...] = ("战斗", "逃跑", "对话", "决策", "移动", "情感", "其他")
VALID_EMOTION_SCORES: tuple[str, ...] = (
    "strong_positive",
    "mild_positive",
    "neutral",
    "mild_negative",
    "strong_negative",
)
VALID_ENTITY_TYPES: tuple[str, ...] = ("character", "group", "organization", "creature", "artifact")
VALID_CLUE_TYPES: tuple[str, ...] = (
    "none",
    "self_introduction",
    "named_by_other",
    "alias_revealed",
    "appearance_desc",
    "unique_body_marker",
    "kinship_identity",
    "naming_scene",
)
VALID_EVENT_TYPES: tuple[str, ...] = ("冲突", "铺垫", "转折")
VALID_FORESHADOWING_TYPES: tuple[str, ...] = ("物件", "对话", "场景", "人物行为", "其他")

SYMMETRIC_RELATION_TYPES: frozenset[str] = frozenset({"家族", "友情", "盟友"})

VALID_RELATION_TYPES: frozenset[str] = frozenset({"家族", "师徒", "敌对", "盟友", "友情", "爱慕", "主从", "利益"})

VALID_CHANGE_TYPES: frozenset[str] = frozenset({"新建", "强化", "弱化", "断裂"})

DIRECTIONALITY_DIRECTED: Literal["directed"] = "directed"
DIRECTIONALITY_SYMMETRIC: Literal["symmetric"] = "symmetric"
type Directionality = Literal["directed", "symmetric"]

__all__ = [
    "EMOTION_SCORE_MAPPING",
    "VALID_ROLE_FUNCTIONS",
    "VALID_ACTION_TYPES",
    "VALID_EMOTION_SCORES",
    "VALID_ENTITY_TYPES",
    "VALID_CLUE_TYPES",
    "VALID_EVENT_TYPES",
    "VALID_FORESHADOWING_TYPES",
    "SYMMETRIC_RELATION_TYPES",
    "VALID_RELATION_TYPES",
    "VALID_CHANGE_TYPES",
    "DIRECTIONALITY_DIRECTED",
    "DIRECTIONALITY_SYMMETRIC",
    "Directionality",
]
