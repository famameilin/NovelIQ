
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from src.models.local.schema import ChunkAnnotation
    from src.rag.evidence_types import EvidenceBundle

from src.models.local.schema import CharacterSnapshot, DialogueSnapshot

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


def _collect_names_from_disambig_candidate(content: str) -> set[str]:
    if not content:
        return set()

    names: set[str] = set()
    body = content.strip()

    if "「" in body and "」" in body:
        _, _, tail = body.partition("「")
        source_name, _, _ = tail.partition("」")
        source_name = source_name.strip()
        if source_name:
            names.add(source_name)

    _, separator, candidates_text = body.partition("：")
    if not separator:
        return names

    for candidate in candidates_text.split("、"):
        normalized = candidate.strip().strip("。；;")
        if normalized:
            names.add(normalized)
    return names


def _collect_names_from_evidence_bundle(bundle: EvidenceBundle | None) -> set[str]:
    if bundle is None:
        return set()

    names: set[str] = set()

    structured_alias_map = getattr(bundle, "structured_alias_map", None)
    if callable(structured_alias_map):
        alias_map = structured_alias_map()
        if isinstance(alias_map, dict):
            names.update(name for name in alias_map.keys() if isinstance(name, str) and name)
            names.update(name for name in alias_map.values() if isinstance(name, str) and name)

    for item in getattr(bundle, "structured_evidence", []):
        if item.evidence_type == "alias_mapping":
            alias = str(item.metadata.get("alias", "")).strip()
            canonical = str(item.metadata.get("canonical", "")).strip()
            if alias:
                names.add(alias)
            if canonical:
                names.add(canonical)
        elif item.evidence_type in {"canonical_entity", "entity_type"}:
            name = str(item.metadata.get("name", item.content)).strip()
            if name:
                names.add(name)

    for item in getattr(bundle, "local_evidence", []):
        if item.evidence_type == "active_entity":
            name = str(item.metadata.get("name", item.content)).strip()
            if name:
                names.add(name)
        elif item.evidence_type == "disambig_candidate":
            names.update(_collect_names_from_disambig_candidate(item.content))

    snapshot = getattr(bundle, "level1_snapshot", None)
    if snapshot is not None:
        names.update(mapping.alias for mapping in snapshot.alias_mappings if mapping.alias)
        names.update(mapping.canonical for mapping in snapshot.alias_mappings if mapping.canonical)
        names.update(entity.name for entity in snapshot.canonical_entities if entity.name)
        names.update(item.name for item in snapshot.entity_types if item.name)

    return names


def validate_names_in_sources(names: list[str], sources: dict) -> list[str]:
    """
    验证人名是否在合法来源中出现

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
    evidence_bundle_names = _collect_names_from_evidence_bundle(sources.get("evidence_bundle"))

    appearance_names = [ca.get("raw_name") for ca in character_appearances if ca.get("raw_name")]

    logger.debug(
        "validate_names_in_sources: "
        "names={} text_len={} prev_chunk_len={} "
        "active_entities={} alias_map_keys={} evidence_bundle_names={} "
        "next_chunk_len={} appearance_names={}",
        names,
        len(text),
        len(prev_chunk_text),
        active_entities,
        list(alias_map.keys()) if alias_map else [],
        sorted(evidence_bundle_names),
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

        if not is_valid and evidence_bundle_names and name in evidence_bundle_names:
            is_valid = True
            logger.debug("validate_names_in_sources: name='{}' found in evidence_bundle", name)

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

    new_dialogues: list[DialogueSnapshot] = []
    for dialogue in annotation.dialogues:
        new_speaker: list[str] | None = None
        if dialogue.speaker:
            new_speaker = [name_mapping.get(s, s) for s in dialogue.speaker]
        new_dialogues.append(
            DialogueSnapshot(
                speaker=new_speaker,
                content=dialogue.content if hasattr(dialogue, "content") else "",
                tone=dialogue.tone if hasattr(dialogue, "tone") else None,
                identity_clue=dialogue.identity_clue if hasattr(dialogue, "identity_clue") else None,
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
        dialogues=new_dialogues,
    )


def validate_character_appearances_sync(
    character_appearances: list,
    characters: list[CharacterSnapshot],
) -> list[str]:
    """
    校验 character_appearances 中明确人名线索是否同步到 characters 列表

    说明: 检查 character_appearances 中 named_by_other / self_introduction / alias_revealed 类型
         的名字是否出现在 characters 列表中，如果没有则返回缺失列表

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
            logger.debug(f"[validate_character_appearances_sync] 角色已存在: raw_name={raw_name}")
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

    说明: 检查 characters, dialogues 中引用的角色是否都在 existing_characters 中

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
        f"dialogues_count={len(annotation.dialogues)}"
    )

    for char in annotation.characters:
        if char.name and char.name not in existing_characters:
            missing_names.add(char.name)
            logger.debug(f"[validate_chunk_annotation] 发现缺失角色: {char.name} (在 characters 中)")

    for dialogue in annotation.dialogues:
        if dialogue.speaker:
            for s in dialogue.speaker:
                if s not in existing_characters:
                    missing_names.add(s)
                    logger.debug(f"[validate_chunk_annotation] 发现缺失角色: {s} (在 dialogues.speaker 中)")

    is_valid = len(missing_names) == 0
    if not is_valid:
        logger.warning(
            f"[validate_chunk_annotation] "
            f"chunk_id={getattr(annotation, 'chunk_id', 'unknown')} "
            f"发现缺失角色: {missing_names}"
        )

    return is_valid, sorted(missing_names)
