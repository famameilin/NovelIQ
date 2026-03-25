"""
标注构建模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分parser.py
说明: 提取标注构建相关逻辑
"""

from __future__ import annotations

from typing import Any, Dict, List

from src.config.schemas import ANNOTATION_CONFIG

from ..schema import (
    ChunkAnnotation,
    CharacterSnapshot,
    CharacterAppearance,
    RelationChangeSnapshot,
    ClueType,
    ForeshadowingType,
)

# 使用配置类替代魔法字符串
_VALID_ROLE_FUNCTIONS = ANNOTATION_CONFIG.valid_role_functions or []
_VALID_ACTION_TYPES = ANNOTATION_CONFIG.valid_action_types or []
_VALID_EMOTION_SCORES = ANNOTATION_CONFIG.valid_emotion_scores or []
_VALID_RELATION_TYPES = ANNOTATION_CONFIG.valid_interpersonal_relation_types or []
_VALID_CLUE_TYPES = ANNOTATION_CONFIG.valid_clue_types or []
_VALID_EMOTIONAL_VALENCES = ANNOTATION_CONFIG.valid_emotion_scores or []
_VALID_EVENT_TYPES = ANNOTATION_CONFIG.valid_event_types or []
_VALID_FORESHADOWING_TYPES = ANNOTATION_CONFIG.valid_foreshadowing_types or []


def make_empty_annotation() -> ChunkAnnotation:
    """创建空标注对象"""
    return ChunkAnnotation(
        emotional_valence="neutral",
        event_type="铺垫",
        pivot_moment=False,
        cliffhanger=False,
        has_foreshadowing=False,
        foreshadowing_type=None,
        foreshadowing_desc="",
        character_appearances=[],
        chunk_summary="",
    )


def _parse_characters(data: Dict[str, Any]) -> List[CharacterSnapshot]:
    """
    解析角色快照列表

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: code-quality-refactor - 提取build_annotation中的字符处理逻辑
    """
    characters = []
    for c in data.get("characters", []):
        if not isinstance(c, dict):
            continue

        role_function = c.get("role_function", "其他")
        if role_function not in _VALID_ROLE_FUNCTIONS:
            role_function = "其他"

        action_type = c.get("action_type", "其他")
        if action_type not in _VALID_ACTION_TYPES:
            action_type = "其他"

        emotion_score = c.get("emotion_score", "neutral")
        if emotion_score not in _VALID_EMOTION_SCORES:
            emotion_score = "neutral"

        characters.append(
            CharacterSnapshot(
                name=c.get("name", ""),
                role_function=role_function,
                action=c.get("action", ""),
                action_type=action_type,
                emotion_score=emotion_score,
            )
        )
    return characters


def _parse_relations(data: Dict[str, Any]) -> List[RelationChangeSnapshot]:
    """
    解析关系变化快照列表

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: code-quality-refactor - 提取build_annotation中的关系处理逻辑
    说明: 过滤 change 为 "无变化" 的记录
    """
    relations = []
    for r in data.get("relations", []):
        if not isinstance(r, dict):
            continue

        change = r.get("change", "无变化")
        if change == "无变化":
            continue

        rel_type = r.get("type", "利益")
        if rel_type not in _VALID_RELATION_TYPES:
            rel_type = "利益"

        relations.append(
            RelationChangeSnapshot(
                from_name=r.get("from", ""),
                to_name=r.get("to", ""),
                type=rel_type,
                change=change,
            )
        )
    return relations


def _parse_character_appearances(data: Dict[str, Any]) -> List[CharacterAppearance]:
    """
    解析角色出场信息列表

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: code-quality-refactor - 提取build_annotation中的角色出场处理逻辑
    说明: 过滤 clue_type 为 "none" 的记录
    """
    appearances = []
    for ca in data.get("character_appearances", []):
        if not isinstance(ca, dict):
            continue

        clue_type_raw = ca.get("clue_type", "none")
        if clue_type_raw == "none":
            continue

        clue_type: ClueType = clue_type_raw if clue_type_raw in _VALID_CLUE_TYPES else "none"
        if clue_type == "none":
            continue

        appearances.append(
            CharacterAppearance(
                raw_name=ca.get("raw_name", ""),
                identity_clue=ca.get("identity_clue", ""),
                clue_type=clue_type,
            )
        )
    return appearances


def _normalize_emotional_valence(valence: Any) -> str:
    """
    标准化情感倾向值

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: code-quality-refactor - 提取build_annotation中的情感倾向处理逻辑
    说明: 支持v1（三档）到v2（五档）的转换

    修改时间: 2026-03-25
    修改者: TraeAI
    任务: upgrade-emotional-valence-to-five-level
    修改内容: 升级为五档枚举，v2为五档，v1为旧三档（兼容历史数据）
    """
    if valence in _VALID_EMOTIONAL_VALENCES:
        return valence

    return "neutral"


def _parse_event_type(event_type: Any) -> str:
    """
    解析事件类型

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: code-quality-refactor - 提取build_annotation中的事件类型处理逻辑
    """
    return event_type if event_type in _VALID_EVENT_TYPES else "铺垫"


def _parse_foreshadowing_type(
    has_foreshadowing: bool,
    foreshadowing_type_raw: Any,
) -> ForeshadowingType | None:
    """
    解析伏笔类型

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: code-quality-refactor - 提取build_annotation中的伏笔类型处理逻辑
    """
    if has_foreshadowing and foreshadowing_type_raw in _VALID_FORESHADOWING_TYPES:
        return foreshadowing_type_raw
    return None


def build_annotation(data: Dict[str, Any]) -> ChunkAnnotation:
    """
    构建标注结果

    修改时间: 2026-03-17
    修改者: TraeAI
    任务: code-quality-refactor - 重构build_annotation
    修改内容:
    - 提取各字段解析逻辑到独立函数
    - 使用常量定义替代魔法字符串
    - 简化主函数逻辑
    """
    has_foreshadowing = data.get("has_foreshadowing", False)

    return ChunkAnnotation(
        emotional_valence=_normalize_emotional_valence(data.get("emotional_valence", "neutral")),
        event_type=_parse_event_type(data.get("event_type", "铺垫")),
        pivot_moment=data.get("pivot_moment", False),
        cliffhanger=data.get("cliffhanger", False),
        has_foreshadowing=has_foreshadowing,
        foreshadowing_type=_parse_foreshadowing_type(
            has_foreshadowing, data.get("foreshadowing_type")
        ),
        foreshadowing_desc=data.get("foreshadowing_desc", ""),
        characters=_parse_characters(data),
        relations=_parse_relations(data),
        character_appearances=_parse_character_appearances(data),
        chunk_summary=data.get("chunk_summary", ""),
    )
