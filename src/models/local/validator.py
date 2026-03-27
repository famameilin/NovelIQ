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

修改时间: 2026-03-21
修改者: TraeAI
任务: fix-validate-names-from-character-appearances
修改内容: 增加 character_appearances 检查，支持名字变体验证

修改时间: 2026-03-27
修改者: TraeAI
任务: fix-character-dangling-reference
修改内容: 新增 validate_character_appearances_sync 和 validate_chunk_annotation 校验函数
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from src.models.local.schema import ChunkAnnotation

from src.models.local.schema import CharacterSnapshot, DialogueSnapshot, RelationChangeSnapshot

_ANONYMOUS_NAME_PATTERN = re.compile(r"^匿名_C\d+_\d+$")

EXPLICIT_NAME_CLUE_TYPES = {"named_by_other", "self_introduction", "alias_revealed"}


def is_anonymous_name(name: str) -> bool:
    """
    判断是否为匿名占位名

    Args:
        name: 人名

    Returns:
        是否为匿名占位名（格式：匿名_C{chunk_id}_{index}）
    """
    return bool(_ANONYMOUS_NAME_PATTERN.match(name))


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


def validate_names_in_sources(names: list[str], sources: dict) -> list[str]:
    """
    验证人名是否在合法来源中出现

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 统一字段命名，使用 prev_chunk_text 和 next_chunk_text

    修改时间: 2026-03-21
    修改者: TraeAI
    任务: fix-validate-names-from-character-appearances
    修改内容: 增加 character_appearances 检查，支持名字变体验证

    Args:
        names: 需要验证的人名列表
        sources: 包含以下键的字典
            - text: 待分析文本
            - prev_chunk_text: 前文chunk文本（可选）
            - active_entities: 活跃实体列表（可选，list[str]）
            - alias_map: 别名映射表（可选，dict[str, str]）
            - next_chunk_text: 后文chunk文本（可选）
            - character_appearances: 角色出现记录列表（可选，list[dict]）

    Returns:
        不在任何合法来源中出现的无效人名列表
    """
    invalid_names: list[str] = []

    text = sources.get("text", "")
    prev_chunk_text = sources.get("prev_chunk_text") or ""
    active_entities = sources.get("active_entities") or []
    alias_map = sources.get("alias_map") or {}
    next_chunk_text = sources.get("next_chunk_text") or ""
    character_appearances = sources.get("character_appearances") or []

    appearance_names = [ca.get("raw_name") for ca in character_appearances if ca.get("raw_name")]

    logger.debug(
        "validate_names_in_sources: names={} text_len={} prev_chunk_len={} active_entities={} alias_map_keys={} next_chunk_len={} appearance_names={}",
        names,
        len(text),
        len(prev_chunk_text),
        active_entities,
        list(alias_map.keys()) if alias_map else [],
        len(next_chunk_text),
        appearance_names,
    )

    for name in names:
        if is_anonymous_name(name):
            logger.debug("validate_names_in_sources: skipping anonymous name='{}'", name)
            continue

        is_valid = False

        if text and name in text:
            is_valid = True
            logger.debug("validate_names_in_sources: name='{}' found in text", name)

        if not is_valid and prev_chunk_text and name in prev_chunk_text:
            is_valid = True
            logger.debug("validate_names_in_sources: name='{}' found in prev_chunk_text", name)

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

        if not is_valid and next_chunk_text and name in next_chunk_text:
            is_valid = True
            logger.debug("validate_names_in_sources: name='{}' found in next_chunk_text", name)

        if not is_valid and appearance_names:
            if name in appearance_names:
                is_valid = True
                logger.debug("validate_names_in_sources: name='{}' found in character_appearances", name)
            else:
                for appearance_name in appearance_names:
                    if appearance_name in name and appearance_name != name:
                        is_valid = True
                        logger.debug(
                            "validate_names_in_sources: name='{}' contains appearance_name='{}'",
                            name,
                            appearance_name,
                        )
                        break

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


def replace_invalid_names_with_anonymous(
    annotation: ChunkAnnotation, invalid_names: list[str], chunk_id: int
) -> ChunkAnnotation:
    """
    将无效人名替换为匿名占位符

    创建时间: 2025-03-11
    创建者: TraeAI
    任务: 人名验证和匿名占位符处理

    修改时间: 2026-03-16
    修改者: TraeAI
    任务: 迁移数据模型至 Pydantic
    修改内容: 从 dataclass 迁移至 Pydantic BaseModel

    Args:
        annotation: 分块标注数据
        invalid_names: 无效人名列表
        chunk_id: chunk ID

    Returns:
        替换后的标注数据
    """
    from src.models.local.schema import ChunkAnnotation as CA

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
        new_speaker = name_mapping.get(dialogue.speaker, dialogue.speaker) if dialogue.speaker else dialogue.speaker
        new_dialogues.append(
            DialogueSnapshot(
                speaker=new_speaker,
            )
        )

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


def validate_character_appearances_sync(
    character_appearances: list,
    characters: list[CharacterSnapshot],
) -> list[str]:
    """
    校验 character_appearances 中明确人名线索是否同步到 characters 列表

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: fix-character-dangling-reference
    说明: 检查 character_appearances 中 named_by_other / self_introduction / alias_revealed 类型
         的名字是否出现在 characters 列表中，如果没有则返回缺失列表。

    Args:
        character_appearances: 角色出场信息列表
        characters: 角色快照列表

    Returns:
        缺失的角色名列表
    """
    character_names = {c.name for c in characters}
    missing_names: list[str] = []

    logger.debug(
        f"[validate_character_appearances_sync] 开始校验, "
        f"character_appearances_count={len(character_appearances)}, "
        f"characters_count={len(characters)}"
    )

    for appearance in character_appearances:
        clue_type = getattr(appearance, "clue_type", None)
        if clue_type not in EXPLICIT_NAME_CLUE_TYPES:
            logger.debug(
                f"[validate_character_appearances_sync] 跳过非明确人名线索: "
                f"raw_name={getattr(appearance, 'raw_name', 'N/A')}, clue_type={clue_type}"
            )
            continue

        raw_name = getattr(appearance, "raw_name", None)
        if not raw_name:
            continue

        if raw_name in character_names:
            logger.debug(
                f"[validate_character_appearances_sync] 角色已存在: raw_name={raw_name}"
            )
            continue

        missing_names.append(raw_name)
        logger.warning(
            f"[validate_character_appearances_sync] 发现角色 '{raw_name}' "
            f"clue_type={clue_type}, "
            f"identity_clue={getattr(appearance, 'identity_clue', 'N/A')}, "
            f"需要同步到 characters 列表"
        )

    if missing_names:
        logger.warning(
            f"[validate_character_appearances_sync] 发现 {len(missing_names)} 个角色需要同步: {missing_names}"
        )

    return missing_names


def validate_chunk_annotation(
    annotation: ChunkAnnotation,
    existing_characters: set[str],
) -> tuple[bool, list[str]]:
    """
    校验单个 chunk 标注的一致性

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: fix-character-dangling-reference
    说明: 检查 characters, relations, dialogues 中引用的角色是否都在 existing_characters 中

    Args:
        annotation: Chunk 标注数据
        existing_characters: 已存在的角色名集合

    Returns:
        tuple[bool, list[str]]: 是否通过校验, 缺失的角色名列表
    """
    missing_names: set[str] = set()

    logger.debug(
        f"[validate_chunk_annotation] 开始校验 chunk_id={getattr(annotation, 'chunk_id', 'unknown')}, "
        f"characters_count={len(annotation.characters)}, "
        f"relations_count={len(annotation.relations)}, "
        f"dialogues_count={len(annotation.dialogues)}"
    )

    for char in annotation.characters:
        if char.name and char.name not in existing_characters:
            missing_names.add(char.name)
            logger.debug(
                f"[validate_chunk_annotation] 发现缺失角色: {char.name} (在 characters 中)"
            )

    for rel in annotation.relations:
        if rel.from_name and rel.from_name not in existing_characters:
            missing_names.add(rel.from_name)
            logger.debug(
                f"[validate_chunk_annotation] 发现缺失角色: {rel.from_name} (在 relations.from_name 中)"
            )
        if rel.to_name and rel.to_name not in existing_characters:
            missing_names.add(rel.to_name)
            logger.debug(
                f"[validate_chunk_annotation] 发现缺失角色: {rel.to_name} (在 relations.to_name 中)"
            )

    for dialogue in annotation.dialogues:
        if dialogue.speaker and dialogue.speaker not in existing_characters:
            missing_names.add(dialogue.speaker)
            logger.debug(
                f"[validate_chunk_annotation] 发现缺失角色: {dialogue.speaker} (在 dialogues.speaker 中)"
            )

    is_valid = len(missing_names) == 0
    if not is_valid:
        logger.warning(
            f"[validate_chunk_annotation] chunk_id={getattr(annotation, 'chunk_id', 'unknown')} 发现缺失角色: {missing_names}"
        )

    return is_valid, sorted(missing_names)
