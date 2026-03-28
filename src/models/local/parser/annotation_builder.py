"""
标注构建模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分parser.py
说明: 提取标注构建相关逻辑

修改时间: 2026-03-26
修改者: TraeAI
任务: disambiguation-evidence-grading
修改内容: 添加摘要质量校验函数
"""

from __future__ import annotations

import re
from typing import Any

from loguru import logger

from src.config.schemas import ANNOTATION_CONFIG

from ..schema import (
    CharacterAppearance,
    CharacterSnapshot,
    ChunkAnnotation,
    ClueType,
    ForeshadowingType,
    LocationAppearance,
    RelationChangeSnapshot,
)

_VALID_ROLE_FUNCTIONS = ANNOTATION_CONFIG.valid_role_functions or []
_VALID_ACTION_TYPES = ANNOTATION_CONFIG.valid_action_types or []
_VALID_EMOTION_SCORES = ANNOTATION_CONFIG.valid_emotion_scores or []
_VALID_RELATION_TYPES = ANNOTATION_CONFIG.valid_interpersonal_relation_types or []
_VALID_CLUE_TYPES = ANNOTATION_CONFIG.valid_clue_types or []
_VALID_EMOTIONAL_VALENCES = ANNOTATION_CONFIG.valid_emotion_scores or []
_VALID_EVENT_TYPES = ANNOTATION_CONFIG.valid_event_types or []
_VALID_FORESHADOWING_TYPES = ANNOTATION_CONFIG.valid_foreshadowing_types or []

_SUMMARY_MIN_LENGTH = 30
_SUMMARY_MAX_LENGTH = 60
_NAME_ADHESION_PATTERN = re.compile(r"(?:灰衣|白衣|黑衣|青衣|红衣|紫衣)人[\u4e00-\u9fa5]{2,}(?:近看|觉得|发现|看见)")


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


_ROLE_FUNCTION_PRIORITY = {
    "主体": 6,
    "客体": 5,
    "帮助者": 4,
    "反对者": 3,
    "发送者": 2,
    "接收者": 1,
    "其他": 0,
}


def _deduplicate_characters(characters: list[CharacterSnapshot]) -> list[CharacterSnapshot]:
    """
    角色去重：同一人物只保留一条记录

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: fix-duplicate-characters-in-chunk
    说明: 当同一人物出现多次时，按角色功能优先级选择保留哪条记录

    去重规则：
    1. 按角色功能优先级选择：主体 > 客体 > 帮助者 > 反对者 > 发送者 > 接收者
    2. 优先级相同时，保留第一条记录
    """
    if not characters:
        return characters

    seen: dict[str, CharacterSnapshot] = {}
    for char in characters:
        if not char.name:
            continue
        if char.name not in seen:
            seen[char.name] = char
        else:
            existing_priority = _ROLE_FUNCTION_PRIORITY.get(seen[char.name].role_function, 0)
            current_priority = _ROLE_FUNCTION_PRIORITY.get(char.role_function, 0)
            if current_priority > existing_priority:
                seen[char.name] = char

    return list(seen.values())


def _parse_characters(data: dict[str, Any]) -> list[CharacterSnapshot]:
    """
    解析角色快照列表

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: code-quality-refactor - 提取build_annotation中的字符处理逻辑

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: fix-duplicate-characters-in-chunk
    修改内容: 添加去重逻辑，同一人物只保留一条记录
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
    return _deduplicate_characters(characters)


def _parse_relations(data: dict[str, Any]) -> list[RelationChangeSnapshot]:
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


def _parse_character_appearances(data: dict[str, Any]) -> list[CharacterAppearance]:
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


def _parse_location_appearances(data: dict[str, Any]) -> list[LocationAppearance]:
    """
    解析地点出场信息列表

    创建时间: 2026-03-28
    创建者: TraeAI
    任务: implement-location-entity-type
    说明: 从 Phase1 标注结果中提取地点信息
    """
    appearances = []
    for loc in data.get("location_appearances", []):
        if not isinstance(loc, dict):
            continue

        raw_name = loc.get("raw_name", "")
        if not raw_name:
            continue

        location_type = loc.get("location_type")
        if location_type not in ("room", "building", "area"):
            location_type = None

        appearances.append(
            LocationAppearance(
                raw_name=raw_name,
                location_type=location_type,
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


def validate_summary_quality(summary: str) -> tuple[bool, list[str]]:
    """
    校验摘要质量

    创建时间: 2026-03-26
    创建者: TraeAI
    任务: disambiguation-evidence-grading
    说明: 检查摘要长度和名字粘连问题

    Args:
        summary: 摘要文本

    Returns:
        (是否通过校验, 问题列表)
    """
    issues: list[str] = []

    if not summary:
        return True, issues

    length = len(summary)
    if length < _SUMMARY_MIN_LENGTH:
        issues.append(f"摘要过短（{length}字），建议{_SUMMARY_MIN_LENGTH}-{_SUMMARY_MAX_LENGTH}字")
    elif length > _SUMMARY_MAX_LENGTH:
        issues.append(f"摘要过长（{length}字），建议{_SUMMARY_MIN_LENGTH}-{_SUMMARY_MAX_LENGTH}字")

    adhesion_matches = _NAME_ADHESION_PATTERN.findall(summary)
    if adhesion_matches:
        issues.append(f"疑似名字粘连：{', '.join(adhesion_matches[:3])}")

    return len(issues) == 0, issues


def _validate_and_log_summary(summary: str) -> str:
    """
    校验摘要并记录日志

    创建时间: 2026-03-26
    创建者: TraeAI
    任务: disambiguation-evidence-grading
    说明: 校验摘要质量，有问题时记录警告日志
    """
    if not summary:
        return summary

    passed, issues = validate_summary_quality(summary)
    if not passed:
        logger.warning(f"摘要质量校验未通过: {'; '.join(issues)} | 摘要: {summary[:50]}...")

    return summary


def build_annotation(data: dict[str, Any]) -> ChunkAnnotation:
    """
    构建标注结果

    修改时间: 2026-03-17
    创建者: TraeAI
    任务: code-quality-refactor - 重构build_annotation
    修改内容:
    - 提取各字段解析逻辑到独立函数
    - 使用常量定义替代魔法字符串
    - 简化主函数逻辑

    修改时间: 2026-03-26
    修改者: TraeAI
    任务: disambiguation-evidence-grading
    修改内容: 添加摘要质量校验
    """
    has_foreshadowing = data.get("has_foreshadowing", False)
    raw_summary = data.get("chunk_summary", "")
    validated_summary = _validate_and_log_summary(raw_summary)

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
        location_appearances=_parse_location_appearances(data),
        chunk_summary=validated_summary,
    )
