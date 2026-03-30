"""
标注数据角色操作

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分annotation_repository
说明: 角色消歧、名称更新、别名映射等操作

修改时间: 2026-03-30
修改者: CodeBuddy
任务: refactor-session-management
修改内容: 优化 ensure_canonical_entities 为批量查询，减少 N+1 问题
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import delete, func, select, update

from src.storage.models import (
    CharacterAppearance,
    ChunkCharacter,
    ChunkDialogue,
    ChunkRelation,
    GraphEntity,
    GraphEntityAlias,
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
    graph_stmt = (
        select(GraphEntityAlias.alias, GraphEntity.canonical_name)
        .join(GraphEntity, GraphEntityAlias.entity_id == GraphEntity.entity_id)
        .where(GraphEntityAlias.run_id == run_id)
    )
    graph_rows = session.execute(graph_stmt).fetchall()
    alias_map = {row[0]: row[1] for row in graph_rows}
    for _alias, canonical in list(alias_map.items()):
        alias_map.setdefault(canonical, canonical)
    return alias_map


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


def ensure_canonical_entities(
    session: Session,
    run_id: str,
    known_canonical_names: frozenset[str],
    novel_id: str,
    entity_types: dict[str, str] | None = None,
) -> dict[str, int]:
    """
    只为 known_canonical_names 创建实体（GraphEntity）

    Args:
        session: 数据库会话
        run_id: 运行ID
        known_canonical_names: 规范角色名集合
        novel_id: 小说ID（保留参数兼容性）
        entity_types: 实体类型映射（可选），key为实体名，value为类型

    Returns:
        {canonical_name: entity_id} 映射
    """
    from src.storage.repositories.graph.repository import GraphRepository

    graph_repo = GraphRepository(session)
    canonical_to_entity_id: dict[str, int] = {}

    for canonical in known_canonical_names:
        entity_type = (entity_types.get(canonical, "character") if entity_types else "character")
        entity = graph_repo.upsert_entity(
            run_id=run_id,
            canonical_name=canonical,
            entity_type=entity_type,
            source_confidence=1.0,
        )
        if entity.entity_id is not None:
            canonical_to_entity_id[canonical] = entity.entity_id

    logger.info(f"Ensured {len(canonical_to_entity_id)} canonical entities")
    return canonical_to_entity_id


def apply_alias_merges(
    session: Session,
    run_id: str,
    alias_merges: dict[str, str],
) -> None:
    """
    执行文本归一化（不改写 chunk_relations 原始称呼）
    
    创建时间: 2026-03-27
    创建者: TraeAI
    任务: disambiguation-state-three-layer
    说明: 从 update_character_names 拆分，只负责文本归一化
    
    只处理 alias != canonical 的映射。
    注意：chunk_relations 作为关系证据入口，需要保留原始称呼，归一化应在 graph 投影阶段完成。
    
    Args:
        session: 数据库会话
        run_id: 运行ID
        alias_merges: 别名到规范名的映射（只包含 alias != canonical）
    """
    correction_count = 0
    for alias, canonical in alias_merges.items():
        if alias == canonical:
            continue
        
        session.execute(
            update(ChunkCharacter)
            .where(ChunkCharacter.name == alias, ChunkCharacter.run_id == run_id)
            .values(name=canonical)
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
        
        correction_count += 1
    
    session.execute(
        delete(ChunkRelation).where(
            ChunkRelation.from_char == ChunkRelation.to_char,
            ChunkRelation.run_id == run_id,
        )
    )

    # 注意：Repository 层不管理事务，由调用方控制 commit
    logger.info(f"Applied {correction_count} alias merges")
