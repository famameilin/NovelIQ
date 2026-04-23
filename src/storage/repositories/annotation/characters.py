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
from sqlalchemy import delete, func, select

from src.storage.models import (
    ChunkCharacter,
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
    alias_map = {row.alias: row.canonical_name for row in graph_rows}
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
    stmt = select(ChunkCharacter.name, func.count().label("appearance_count")).where(ChunkCharacter.run_id == run_id)
    if max_chunk_id is not None:
        stmt = stmt.where(ChunkCharacter.chunk_id <= max_chunk_id)
    stmt = stmt.group_by(ChunkCharacter.name)
    result = session.execute(stmt).fetchall()
    name_counts: dict[str, int] = {}
    for row in result:
        name = row.name
        count = int(row.appearance_count or 0)
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
        entity_type = entity_types.get(canonical, "character") if entity_types else "character"
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


def cleanup_self_loop_relations(
    session: Session,
    run_id: str,
) -> None:
    """
    清理自环关系。

    不再改写 ChunkCharacter.name、ChunkDialogue.speaker、CharacterAppearance.raw_name。
    原始名称是 LLM 从文本中提取的真实数据，不可逆修改会导致
    project_graph_tables(rebuild) 后别名关系永久丢失。

    归一化由 graph_projection 层通过 DisambiguationState.alias_merges 完成，
    写入 graph_entity_aliases 表。

    修改时间: 2026-04-01
    修改者: CodeBuddy
    修改内容: 移除 ChunkCharacter/ChunkDialogue/CharacterAppearance 的归一化写入，
              保留自环关系清理。

    修改时间: 2026-04-02
    修改者: TraeAI
    任务: fix-disambiguation-code-quality
    修改内容: 重命名为 cleanup_self_loop_relations，移除 alias_merges 参数

    Args:
        session: 数据库会话
        run_id: 运行ID
    """
    result = session.execute(
        delete(ChunkRelation).where(
            ChunkRelation.from_char == ChunkRelation.to_char,
            ChunkRelation.run_id == run_id,
        )
    )

    deleted_count = result.rowcount if hasattr(result, "rowcount") else 0
    logger.info(f"Cleaned {deleted_count} self-loop relations for run {run_id}")
