"""
标注构建模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分parser.py
说明: 提取标注构建相关逻辑

修改时间: 2026-03-29
修改者: TraeAI
任务: remove-unused-annotation-fields
修改内容: 移除摘要质量校验函数（不再使用）

修改时间: 2026-04-20
修改者: Codex
任务: runtime-behavior-settings
修改内容: 移除对 ANNOTATION_CONFIG 的依赖，静态校验枚举统一改从 constants 读取
"""

from __future__ import annotations

from typing import Any

from src.config.constants import (
    VALID_ACTION_TYPES,
    VALID_EMOTION_SCORES,
    VALID_EVENT_TYPES,
    VALID_FORESHADOWING_TYPES,
    VALID_ROLE_FUNCTIONS,
)

from ..schema import (
    CharacterSnapshot,
    ChunkAnnotation,
    ForeshadowingType,
    LocationAppearance,
)

_VALID_ROLE_FUNCTIONS = set(VALID_ROLE_FUNCTIONS)
_VALID_ACTION_TYPES = set(VALID_ACTION_TYPES)
_VALID_EMOTION_SCORES = set(VALID_EMOTION_SCORES)
_VALID_EMOTIONAL_VALENCES = set(VALID_EMOTION_SCORES)
_VALID_EVENT_TYPES = set(VALID_EVENT_TYPES)
_VALID_FORESHADOWING_TYPES = set(VALID_FORESHADOWING_TYPES)


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

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: remove-unused-annotation-fields
    修改内容: 移除 relations、character_appearances、chunk_summary 字段处理

    修改时间: 2026-03-30
    修改者: TraeAI
    任务: feature/chunk-summary-timeline-only
    修改内容: 恢复 chunk_summary 字段处理，仅用于 Timeline 展示
    """
    has_foreshadowing = data.get("has_foreshadowing", False)

    return ChunkAnnotation(
        emotional_valence=_normalize_emotional_valence(data.get("emotional_valence", "neutral")),
        event_type=_parse_event_type(data.get("event_type", "铺垫")),
        pivot_moment=data.get("pivot_moment", False),
        cliffhanger=data.get("cliffhanger", False),
        chunk_summary=data.get("chunk_summary", ""),
        has_foreshadowing=has_foreshadowing,
        foreshadowing_type=_parse_foreshadowing_type(has_foreshadowing, data.get("foreshadowing_type")),
        foreshadowing_desc=data.get("foreshadowing_desc", ""),
        characters=_parse_characters(data),
        location_appearances=_parse_location_appearances(data),
    )
