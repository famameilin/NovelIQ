"""
标注数据角色操作

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分annotation_repository
说明: 角色消歧、名称更新、别名映射等操作
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert

from src.storage.models import (
    CharacterAppearance,
    ChunkCharacter,
    ChunkDialogue,
    ChunkRelation,
    Entity,
    EntityAlias,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def fetch_alias_map(session: Session, run_id: str) -> dict[str, str]:
    """
    获取别名映射表

    修改时间: 2026-03-20
    修改者: TraeAI
    任务: fix-fetch-alias-map-bug
    修改内容: 修复返回值错误，正确返回 {alias: canonical} 映射

    Returns:
        别名到规范名的映射字典
    """
    stmt = (
        select(EntityAlias.alias, Entity.canonical)
        .join(Entity, EntityAlias.entity_id == Entity.entity_id)
        .where(EntityAlias.alias_type == "disambiguation")
        .where(EntityAlias.run_id == run_id)
    )
    result = session.execute(stmt)
    return {row[0]: row[1] for row in result.fetchall()}


def fetch_all_character_names(
    session: Session,
    run_id: str,
    max_chunk_id: int | None = None,
) -> list[dict[str, str | int]]:
    """
    获取指定运行的所有角色名及出现频次

    只从 chunk_characters 表获取名字，确保只有有明确角色功能的人物才被视为正式角色。
    character_appearances 表仅作为身份线索参考，不直接参与消歧候选。

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: fix-character-dangling-reference
    修改内容: 移除 character_appearances 的合并逻辑，统一角色定义

    Returns:
        [{"name": "角色名", "count": 频次}, ...] 列表
    """
    stmt = select(ChunkCharacter.name, func.count().label("count")).where(ChunkCharacter.run_id == run_id)
    if max_chunk_id is not None:
        stmt = stmt.where(ChunkCharacter.chunk_id <= max_chunk_id)
    stmt = stmt.group_by(ChunkCharacter.name)
    result = session.execute(stmt).fetchall()
    name_counts: dict[str, int] = {}
    for row in result:
        name = row[0]
        count = row[1]
        if name and isinstance(name, str):
            name_counts[name] = name_counts.get(name, 0) + count
    return [{"name": name, "count": count} for name, count in sorted(name_counts.items(), key=lambda x: -x[1])]


def get_normalized_character_names(
    session: Session,
    run_id: str,
    alias_map: dict[str, str] | None = None,
) -> set[str]:
    """
    获取归一化后的角色名集合

    基于 chunk_characters 表和 alias_map 计算归一化后的角色名集合。
    只包含在 chunk_characters 中出现过的角色。

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: fix-character-dangling-reference
    说明: 用于实体创建时验证名字有效性

    Args:
        session: 数据库会话
        run_id: 运行ID
        alias_map: 别名到规范名的映射字典（可选）

    Returns:
        归一化后的角色名集合
    """
    raw_names: set[str] = set()
    for item in fetch_all_character_names(session, run_id):
        name = item["name"]
        if isinstance(name, str):
            raw_names.add(name)
    if not alias_map:
        return raw_names

    normalized_names: set[str] = set()
    for name in raw_names:
        normalized_name = alias_map.get(name, name)
        normalized_names.add(normalized_name)
    return normalized_names


def update_character_names(
    session: Session,
    run_id: str,
    alias_map: dict[str, str],
    novel_id: str = "default",
) -> None:
    """
    更新角色名称（消歧）

    将别名更新为规范名，并创建实体和别名映射记录。

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: fix-character-dangling-reference
    修改内容: 只为在 chunk_characters 中出现的名字创建实体，避免悬空引用

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: remove-display-name-map
    修改内容: 删除 display_name_map 参数，规范名即常用名
    """
    valid_names = get_normalized_character_names(session, run_id, alias_map)
    canonical_to_entity_id: dict[str, int] = {}
    all_names = sorted(set(alias_map.keys()) | set(alias_map.values()))
    for name in all_names:
        final_name = _resolve_final_character_name(name, alias_map)
        if name != final_name:
            _update_character_names_in_tables(session, name, final_name, run_id)
        if final_name not in valid_names:
            logger.debug(f"跳过创建实体: {final_name} 不在 chunk_characters 中")
            continue
        entity_id = _ensure_entity_exists(session, novel_id, final_name, canonical_to_entity_id, run_id)
        if entity_id is not None:
            _create_alias_mapping(session, entity_id, name, final_name, run_id)
    session.execute(
        delete(ChunkRelation).where(
            ChunkRelation.from_char == ChunkRelation.to_char,
            ChunkRelation.run_id == run_id,
        )
    )
    session.commit()


def _resolve_final_character_name(
    name: str,
    alias_map: dict[str, str],
) -> str:
    """
    解析最终角色名

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: remove-display-name-map
    修改内容: 简化函数，规范名即常用名，直接使用 alias_map
    """
    return alias_map.get(name, name)


def _update_character_names_in_tables(session: Session, alias: str, canonical: str, run_id: str) -> None:
    """更新多个表中的角色名（从别名更新为规范名）"""
    session.execute(
        update(ChunkCharacter)
        .where(ChunkCharacter.name == alias, ChunkCharacter.run_id == run_id)
        .values(name=canonical)
    )
    session.execute(
        update(ChunkRelation)
        .where(ChunkRelation.from_char == alias, ChunkRelation.run_id == run_id)
        .values(from_char=canonical)
    )
    session.execute(
        update(ChunkRelation)
        .where(ChunkRelation.to_char == alias, ChunkRelation.run_id == run_id)
        .values(to_char=canonical)
    )
    session.execute(
        update(ChunkDialogue)
        .where(ChunkDialogue.speaker == alias, ChunkDialogue.run_id == run_id)
        .values(speaker=canonical)
    )
    session.execute(
        update(CharacterAppearance)
        .where(CharacterAppearance.raw_name == alias, CharacterAppearance.run_id == run_id)
        .values(raw_name=canonical)
    )


def _ensure_entity_exists(
    session: Session,
    novel_id: str,
    canonical: str,
    canonical_to_entity_id: dict[str, int],
    run_id: str,
) -> int | None:
    """
    确保实体存在，返回实体ID

    Returns:
        实体ID，插入失败则返回 None
    """
    if canonical in canonical_to_entity_id:
        return canonical_to_entity_id[canonical]
    stmt = select(Entity.entity_id).where(
        Entity.novel_id == novel_id,
        Entity.canonical == canonical,
        Entity.run_id == run_id,
    )
    row = session.execute(stmt).fetchone()
    if row:
        canonical_to_entity_id[canonical] = row[0]
        return row[0]
    entity = Entity(
        novel_id=novel_id,
        canonical=canonical,
        entity_type="character",
        first_chunk=None,
        last_chunk=None,
        description=None,
        confidence=1.0,
        run_id=run_id,
    )
    session.add(entity)
    session.flush()
    if entity.entity_id is not None:
        canonical_to_entity_id[canonical] = entity.entity_id
        return entity.entity_id
    return None


def _create_alias_mapping(
    session: Session, entity_id: int, alias: str, canonical: str, run_id: str
) -> None:
    """
    创建别名映射记录

    使用 PostgreSQL 的 INSERT ... ON CONFLICT DO NOTHING 实现 INSERT OR IGNORE 语义。
    """
    alias_type = "disambiguation" if alias != canonical else "canonical"
    alias_value = alias if alias != canonical else canonical
    stmt = insert(EntityAlias).values(
        entity_id=entity_id,
        alias=alias_value,
        alias_type=alias_type,
        source_chunk=None,
        confirm_count=1,
        run_id=run_id,
    ).on_conflict_do_nothing(constraint="uq_entity_aliases_entity_alias")
    session.execute(stmt)


def apply_alias_corrections(session: Session, run_id: str, alias_map: dict[str, str]) -> None:
    """
    用最终消歧结果修正所有标注表里的错误名字

    遍历 alias_map，将所有别名修正为规范名
    """
    correction_count = 0
    for alias, canonical in alias_map.items():
        if alias == canonical:
            continue

        session.execute(
            update(ChunkCharacter)
            .where(ChunkCharacter.name == alias, ChunkCharacter.run_id == run_id)
            .values(name=canonical)
        )

        session.execute(
            update(ChunkRelation)
            .where(ChunkRelation.from_char == alias, ChunkRelation.run_id == run_id)
            .values(from_char=canonical)
        )

        session.execute(
            update(ChunkRelation)
            .where(ChunkRelation.to_char == alias, ChunkRelation.run_id == run_id)
            .values(to_char=canonical)
        )

        session.execute(
            update(CharacterAppearance)
            .where(CharacterAppearance.raw_name == alias, CharacterAppearance.run_id == run_id)
            .values(raw_name=canonical)
        )

        correction_count += 1

    session.commit()
    logger.info(f"applied alias corrections: {correction_count} names updated")


def fetch_character_appearances_for_chunks(
    session: Session, run_id: str, min_chunk_id: int, max_chunk_id: int
) -> list[dict]:
    """
    获取指定chunk_id范围内的所有角色出现记录

    创建时间: 2026-03-21
    创建者: TraeAI
    任务: fix-validate-names-from-character-appearances
    修改内容: 新增函数，用于验证时获取 character_appearances 数据

    Args:
        session: 数据库会话
        run_id: 运行ID
        min_chunk_id: 最小chunk_id（不包含）
        max_chunk_id: 最大chunk_id（包含）

    Returns:
        [{"raw_name": "名字", ...}, ...] 列表
    """
    stmt = (
        select(CharacterAppearance.raw_name)
        .where(CharacterAppearance.run_id == run_id)
        .where(CharacterAppearance.chunk_id >= min_chunk_id)
        .where(CharacterAppearance.chunk_id <= max_chunk_id)
    )
    result = session.execute(stmt)
    return [{"raw_name": row[0]} for row in result.fetchall() if row[0]]
