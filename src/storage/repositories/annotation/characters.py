"""
标注数据角色操作

角色消歧、名称更新、别名映射等操作

优化 ensure_canonical_entities 为批量查询，减少 N+1 问题
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import delete, func, select

from src.models.local.character_reference_policy import (
    CharacterReferenceDecision,
    decide_character_reference,
    filter_global_character_names,
    is_global_character_surface_name,
    is_reference_surface_name,
    normalize_reference_name,
    resolve_global_character_name,
)
from src.storage.models import (
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

    修复返回值错误，正确返回 {alias: canonical} 映射

    修改时间: 2026-04-29
    任务: 角色引用分层重构
    修改原因: 旧 graph_aliases 中可能残留“我 -> 某人”，alias_map 出口必须过滤 reference surface。

    Returns:
        别名到规范名的映射字典
    """
    graph_stmt = (
        select(GraphEntityAlias.alias, GraphEntity.canonical_name)
        .join(GraphEntity, GraphEntityAlias.entity_id == GraphEntity.entity_id)
        .where(GraphEntityAlias.run_id == run_id)
    )
    graph_rows = session.execute(graph_stmt).fetchall()
    alias_map = {
        row.alias: row.canonical_name
        for row in graph_rows
        if not is_reference_surface_name(row.alias) and is_global_character_surface_name(row.canonical_name)
    }
    canonical_names = {
        row.canonical_name
        for row in graph_rows
        if is_global_character_surface_name(row.canonical_name)
    }
    for canonical in canonical_names | set(alias_map.values()):
        alias_map.setdefault(canonical, canonical)
    return alias_map


def fetch_all_character_names(
    session: Session,
    run_id: str,
    max_chunk_id: int | None = None,
) -> list[dict[str, str | int]]:
    """
    获取指定运行的所有角色名及出现频次

    只从 chunk_characters 表获取名字，确保只有有明确角色功能的人物才被视为正式角色
    character_appearances 表仅作为身份线索参考，不直接参与消歧候选

    移除 character_appearances 的合并逻辑，统一角色定义

    修改时间: 2026-04-29
    任务: 角色引用分层重构
    修改原因: 消歧候选只能来自可进入 global character 的名字，未解析代词保留 raw 但不再进入主链。

    Returns:
        [{"name": "角色名", "count": 频次}, ...] 列表
    """
    name_expr = func.coalesce(ChunkCharacter.resolved_global_name, ChunkCharacter.name).label("candidate_name")
    stmt = select(name_expr, func.count().label("appearance_count")).where(ChunkCharacter.run_id == run_id)
    if max_chunk_id is not None:
        stmt = stmt.where(ChunkCharacter.chunk_id <= max_chunk_id)
    stmt = stmt.group_by(name_expr)
    result = session.execute(stmt).fetchall()
    name_counts: dict[str, int] = {}
    for row in result:
        name = resolve_global_character_name(row.candidate_name)
        count = int(row.appearance_count or 0)
        if name and isinstance(name, str):
            name_counts[name] = name_counts.get(name, 0) + count
    return [{"name": name, "count": count} for name, count in sorted(name_counts.items(), key=lambda x: -x[1])]


def fetch_reference_aware_character_names(
    session: Session,
    run_id: str,
    max_chunk_id: int | None = None,
) -> list[dict[str, str | int]]:
    """
    获取 reference-aware 的消歧候选名及出现频次

    修改时间: 2026-04-29
    任务: 角色引用分层重构
    修改原因: incremental/final disambiguation 需要保留未解析 reference surface，
              但已解析引用仍应折叠到 resolved_global_name，不能继续走 global-only 出口。

    Returns:
        [{"name": "候选名", "count": 频次}, ...] 列表
    """
    stmt = select(
        ChunkCharacter.surface_name,
        ChunkCharacter.name,
        ChunkCharacter.resolved_global_name,
    ).where(ChunkCharacter.run_id == run_id)
    if max_chunk_id is not None:
        stmt = stmt.where(ChunkCharacter.chunk_id <= max_chunk_id)

    result = session.execute(stmt).fetchall()
    name_counts: dict[str, int] = {}
    for row in result:
        resolved_global_name = normalize_reference_name(row.resolved_global_name)
        if is_global_character_surface_name(resolved_global_name):
            candidate_name = resolved_global_name
        else:
            candidate_name = normalize_reference_name(row.surface_name) or normalize_reference_name(row.name)
        if not candidate_name:
            continue
        name_counts[candidate_name] = name_counts.get(candidate_name, 0) + 1
    return [{"name": name, "count": count} for name, count in sorted(name_counts.items(), key=lambda x: -x[1])]


def _resolve_history_reference_decision(
    surface_name: str | None,
    *,
    chunk_id: int | None,
    reference_resolutions: dict[str, str],
    existing_resolved_global_name: str | None,
) -> CharacterReferenceDecision:
    """
    修改时间: 2026-04-29
    任务: 角色引用分层重构
    修改原因: 当前状态里已移除的 reference resolution 必须撤销历史行上的旧 resolved 值，
              不能因为行上残留旧实名就继续被 graph/results 误消费。
    """
    normalized_surface = normalize_reference_name(surface_name)
    resolved_global_name = existing_resolved_global_name
    if normalized_surface and is_reference_surface_name(normalized_surface):
        # reference surface 只能相信当前 checkpoint 的解析结果；
        # 如果本轮 map 里已经没有它，说明它已被降级回 unresolved，旧 resolved 值必须清空。
        resolved_global_name = reference_resolutions.get(normalized_surface)
    return decide_character_reference(
        normalized_surface,
        resolved_global_name=resolved_global_name,
        chunk_id=chunk_id,
    )


def apply_reference_resolutions_to_history(
    session: Session,
    run_id: str,
    reference_resolutions: dict[str, str],
    *,
    apply: bool = True,
) -> dict[str, int]:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: reference_resolutions 不能只停留在 checkpoint；需要同步驱动 chunk_* 历史行的 resolved 字段消费。

    Returns:
        受处理的历史行统计，key 为表类型。
    """
    chunk_characters = (
        session.execute(select(ChunkCharacter).where(ChunkCharacter.run_id == run_id)).scalars().all()
    )
    for row in chunk_characters:
        decision = _resolve_history_reference_decision(
            row.surface_name or row.name,
            chunk_id=row.chunk_id,
            reference_resolutions=reference_resolutions,
            existing_resolved_global_name=row.resolved_global_name,
        )
        if apply:
            row.surface_name = decision.surface_name
            row.reference_kind = decision.reference_kind
            row.reference_slot = decision.reference_slot
            row.resolved_global_name = decision.resolved_global_name
            row.global_skip_reason = decision.global_skip_reason

    chunk_dialogues = (
        session.execute(select(ChunkDialogue).where(ChunkDialogue.run_id == run_id)).scalars().all()
    )
    for row in chunk_dialogues:
        existing_by_surface: dict[str, dict[str, object]] = {}
        for item in row.speaker_references or []:
            if isinstance(item, dict) and isinstance(item.get("surface_name"), str):
                existing_by_surface[str(item["surface_name"])] = item

        rebuilt_references: list[dict[str, object]] = []
        for speaker_name in row.speaker or []:
            if not speaker_name:
                continue
            existing_reference = existing_by_surface.get(str(speaker_name))
            existing_resolved_global_name = None
            if existing_reference is not None and isinstance(existing_reference.get("resolved_global_name"), str):
                existing_resolved_global_name = str(existing_reference["resolved_global_name"])
            decision = _resolve_history_reference_decision(
                speaker_name,
                chunk_id=row.chunk_id,
                reference_resolutions=reference_resolutions,
                existing_resolved_global_name=existing_resolved_global_name,
            )
            rebuilt_references.append(
                {
                    "surface_name": decision.surface_name,
                    "reference_kind": decision.reference_kind,
                    "reference_slot": decision.reference_slot,
                    "resolved_global_name": decision.resolved_global_name,
                    "can_enter_global_character": decision.can_enter_global_character,
                    "global_skip_reason": decision.global_skip_reason,
                }
            )
        if apply:
            row.speaker_references = rebuilt_references or None

    chunk_relations = session.execute(select(ChunkRelation).where(ChunkRelation.run_id == run_id)).scalars().all()
    for row in chunk_relations:
        from_decision = _resolve_history_reference_decision(
            row.from_char,
            chunk_id=row.chunk_id,
            reference_resolutions=reference_resolutions,
            existing_resolved_global_name=row.resolved_from_global_name,
        )
        to_decision = _resolve_history_reference_decision(
            row.to_char,
            chunk_id=row.chunk_id,
            reference_resolutions=reference_resolutions,
            existing_resolved_global_name=row.resolved_to_global_name,
        )
        reasons = [
            f"{decision.surface_name}: {decision.global_skip_reason}"
            for decision in (from_decision, to_decision)
            if not decision.can_enter_global_character and decision.global_skip_reason
        ]
        if apply:
            row.from_reference_kind = from_decision.reference_kind
            row.to_reference_kind = to_decision.reference_kind
            row.resolved_from_global_name = from_decision.resolved_global_name
            row.resolved_to_global_name = to_decision.resolved_global_name
            row.reference_skip_reason = "; ".join(reasons) if reasons else None

    return {
        "chunk_characters": len(chunk_characters),
        "chunk_dialogues": len(chunk_dialogues),
        "chunk_relations": len(chunk_relations),
    }


def ensure_canonical_entities(
    session: Session,
    run_id: str,
    known_canonical_names: frozenset[str],
    novel_id: str,
    entity_types: dict[str, str] | None = None,
) -> dict[str, int]:
    """
    只为 known_canonical_names 创建实体（GraphEntity）

    修改时间: 2026-04-29
    任务: 角色引用分层重构
    修改原因: 即使 checkpoint 被历史数据污染，graph entity 创建前也必须经过统一主链准入。

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

    for canonical in filter_global_character_names(known_canonical_names):
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
    清理自环关系

    不再改写 ChunkCharacter.name、ChunkDialogue.speaker、CharacterAppearance.raw_name
    原始名称是 LLM 从文本中提取的真实数据，不可逆修改会导致
    project_graph_tables(rebuild) 后别名关系永久丢失

    归一化由 graph_projection 层通过 DisambiguationState.alias_merges 完成，
    写入 graph_entity_aliases 表

    移除 ChunkCharacter/ChunkDialogue/CharacterAppearance 的归一化写入，
              保留自环关系清理

    重命名为 cleanup_self_loop_relations，移除 alias_merges 参数

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
