"""
创建时间: 2025-03-11
创建者: TraeAI
任务: 人名验证和匿名占位符处理

修改时间: 2026-03-11
修改者: TraeAI
修改内容:
1. 添加 is_anonymous_name 函数判断匿名占位名
2. 验证时跳过匿名占位符（匿名_C{id}_{index} 格式）
3. 添加详细的调试日志，便于排查验证问题
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from src.models.local.schema import ChunkAnnotation

from src.models.local.schema import CharacterSnapshot, DialogueSnapshot, RelationChangeSnapshot

_ANONYMOUS_NAME_PATTERN = re.compile(r"^匿名_C\d+_\d+$")


def is_anonymous_name(name: str) -> bool:
    """
    判断是否为匿名占位名

    Args:
        name: 人名

    Returns:
        是否为匿名占位名（格式：匿名_C{chunk_id}_{index}）
    """
    return bool(_ANONYMOUS_NAME_PATTERN.match(name))


def validate_names_in_sources(names: list[str], sources: dict) -> list[str]:
    """
    验证人名是否在合法来源中出现

    Args:
        names: 需要验证的人名列表
        sources: 包含以下键的字典
            - text: 待分析文本
            - prev_tail_text: 前文尾部文本（可选）
            - active_entities: 活跃实体列表（可选，list[str]）
            - alias_map: 别名映射表（可选，dict[str, str]）
            - next_preview: 后续内容预览（可选）

    Returns:
        不在任何合法来源中出现的无效人名列表
    """
    invalid_names: list[str] = []

    text = sources.get("text", "")
    prev_tail_text = sources.get("prev_tail_text") or ""
    active_entities = sources.get("active_entities") or []
    alias_map = sources.get("alias_map") or {}
    next_preview = sources.get("next_preview") or ""

    logger.debug(
        "validate_names_in_sources: names={} text_len={} prev_tail_len={} active_entities={} alias_map_keys={} next_preview_len={}",
        names,
        len(text),
        len(prev_tail_text),
        active_entities,
        list(alias_map.keys()) if alias_map else [],
        len(next_preview),
    )

    for name in names:
        if is_anonymous_name(name):
            logger.debug("validate_names_in_sources: skipping anonymous name='{}'", name)
            continue

        is_valid = False

        if text and name in text:
            is_valid = True
            logger.debug("validate_names_in_sources: name='{}' found in text", name)

        if not is_valid and prev_tail_text and name in prev_tail_text:
            is_valid = True
            logger.debug("validate_names_in_sources: name='{}' found in prev_tail_text", name)

        if not is_valid and active_entities and name in active_entities:
            is_valid = True
            logger.debug("validate_names_in_sources: name='{}' found in active_entities", name)

        if not is_valid and alias_map:
            if name in alias_map or name in alias_map.values():
                is_valid = True
                logger.debug("validate_names_in_sources: name='{}' found in alias_map", name)
            else:
                for canonical in alias_map.values():
                    if name in canonical and name != canonical:
                        is_valid = True
                        logger.debug("validate_names_in_sources: name='{}' found as substring in alias_map", name)
                        break

        if not is_valid and next_preview and name in next_preview:
            is_valid = True
            logger.debug("validate_names_in_sources: name='{}' found in next_preview", name)

        if not is_valid:
            logger.warning(
                "validate_names_in_sources: name='{}' NOT found in any source, text_preview='{}'",
                name,
                text[:100] if text else "",
            )
            invalid_names.append(name)

    if invalid_names:
        logger.warning(
            "validate_names_in_sources: found {} invalid names: {}",
            len(invalid_names),
            invalid_names,
        )

    return invalid_names


def generate_anonymous_name(chunk_id: int, index: int) -> str:
    """
    生成匿名占位名

    Args:
        chunk_id: chunk ID
        index: 序号

    Returns:
        格式为「匿名_C{chunk_id}_{序号}」的占位名
    """
    return f"匿名_C{chunk_id}_{index}"


def replace_invalid_names_with_anonymous(
    annotation: "ChunkAnnotation", invalid_names: list[str], chunk_id: int
) -> "ChunkAnnotation":
    if not invalid_names:
        return annotation

    name_mapping: dict[str, str] = {}
    for idx, invalid_name in enumerate(invalid_names):
        anonymous_name = generate_anonymous_name(chunk_id, idx)
        name_mapping[invalid_name] = anonymous_name

    new_characters: list[CharacterSnapshot] = []
    for character in annotation.characters:
        new_name = name_mapping.get(character.name, character.name)
        new_characters.append(
            CharacterSnapshot(
                name=new_name,
                role_function=character.role_function,
                action=character.action,
                action_type=character.action_type,
                emotion_score=character.emotion_score,
            )
        )

    new_relations: list[RelationChangeSnapshot] = []
    for relation in annotation.relations:
        new_from = name_mapping.get(relation.from_name, relation.from_name)
        new_to = name_mapping.get(relation.to_name, relation.to_name)
        new_relations.append(
            RelationChangeSnapshot(
                from_name=new_from,
                to_name=new_to,
                type=relation.type,
                change=relation.change,
            )
        )

    new_dialogues: list[DialogueSnapshot] = []
    for dialogue in annotation.dialogues:
        new_speaker = name_mapping.get(dialogue.speaker, dialogue.speaker)
        new_dialogues.append(
            DialogueSnapshot(
                speaker=new_speaker,
            )
        )

    from src.models.local.schema import ChunkAnnotation as CA

    return CA(
        emotional_valence=annotation.emotional_valence,
        event_type=annotation.event_type,
        pivot_moment=annotation.pivot_moment,
        cliffhanger=annotation.cliffhanger,
        has_foreshadowing=annotation.has_foreshadowing,
        foreshadowing_type=annotation.foreshadowing_type,
        foreshadowing_desc=annotation.foreshadowing_desc,
        characters=new_characters,
        relations=new_relations,
        dialogues=new_dialogues,
        character_appearances=annotation.character_appearances,
        chunk_summary=annotation.chunk_summary,
    )
