"""
标注数据角色操作

角色消歧、名称更新、别名映射等操作

优化 ensure_canonical_entities 为批量查询，减少 N+1 问题
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from sqlalchemy import delete, func, select

from src.models.local.character_reference_policy import (
    CharacterReferenceDecision,
    build_reference_resolution_lookup_keys,
    decide_character_reference,
    extract_surface_name_from_reference_slot,
    filter_global_character_names,
    is_global_character_surface_name,
    is_reference_surface_name,
    normalize_reference_name,
    resolve_global_character_name,
)
from src.storage.models import (
    Chunk,
    ChunkCharacter,
    ChunkDialogue,
    ChunkRelation,
    GraphEntity,
    GraphEntityAlias,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

HISTORY_TABLE_SCOPES: frozenset[str] = frozenset({"chunk_characters", "chunk_dialogues", "chunk_relations"})


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


def _resolve_relation_reference_candidate_name(
    endpoint_name: str | None,
    *,
    chunk_id: int | None,
    resolved_global_name: str | None,
) -> str | None:
    """
    创建时间: 2026-05-02
    任务: fix-graph-projection-relations
    新建原因: relation-only endpoint 需要以 slot 级 key 进入消歧候选，
              不能继续把不同 chunk 的“我/他们/它”混成同一个 surface。
    """
    decision = decide_character_reference(
        endpoint_name,
        resolved_global_name=resolved_global_name,
        chunk_id=chunk_id,
    )
    if decision.can_enter_global_character or decision.reference_kind == "global_character":
        return None
    return decision.reference_slot or decision.surface_name or None


def _fetch_character_reference_slots(
    session: Session,
    run_id: str,
    *,
    max_chunk_id: int | None = None,
) -> set[str]:
    """
    创建时间: 2026-05-02
    任务: fix-graph-projection-relations
    新建原因: relation-only endpoint 只应补那些没有经过 chunk_characters 候选入口的 slot；
              这里集中收集已有角色槽位，避免重复把同一引用同时以 surface 和 slot 两种形态送进消歧。
    """
    stmt = select(ChunkCharacter.reference_slot).where(
        ChunkCharacter.run_id == run_id,
        ChunkCharacter.reference_slot.is_not(None),
    )
    if max_chunk_id is not None:
        stmt = stmt.where(ChunkCharacter.chunk_id <= max_chunk_id)
    return {
        normalized_slot
        for normalized_slot in (
            normalize_reference_name(reference_slot)
            for reference_slot in session.execute(stmt).scalars().all()
        )
        if normalized_slot
    }


def fetch_relation_reference_candidates(
    session: Session,
    run_id: str,
    max_chunk_id: int | None = None,
) -> list[dict[str, str | int]]:
    """
    创建时间: 2026-05-02
    任务: fix-graph-projection-relations
    新建原因: 关系端点里的局部引用不会进入 chunk_characters，必须从 chunk_relations
              单独补一条候选入口，才能真正进入 reference 消歧链路。
    """
    existing_character_slots = _fetch_character_reference_slots(session, run_id, max_chunk_id=max_chunk_id)
    stmt = select(
        ChunkRelation.chunk_id,
        ChunkRelation.from_char,
        ChunkRelation.to_char,
        ChunkRelation.resolved_from_global_name,
        ChunkRelation.resolved_to_global_name,
    ).where(ChunkRelation.run_id == run_id)
    if max_chunk_id is not None:
        stmt = stmt.where(ChunkRelation.chunk_id <= max_chunk_id)

    result = session.execute(stmt).fetchall()
    name_counts: dict[str, int] = {}
    for row in result:
        for candidate_name in (
            _resolve_relation_reference_candidate_name(
                row.from_char,
                chunk_id=row.chunk_id,
                resolved_global_name=row.resolved_from_global_name,
            ),
            _resolve_relation_reference_candidate_name(
                row.to_char,
                chunk_id=row.chunk_id,
                resolved_global_name=row.resolved_to_global_name,
            ),
        ):
            if not candidate_name:
                continue
            if candidate_name in existing_character_slots:
                continue
            name_counts[candidate_name] = name_counts.get(candidate_name, 0) + 1
    return [{"name": name, "count": count} for name, count in sorted(name_counts.items(), key=lambda x: -x[1])]


def fetch_relation_reference_contexts(
    session: Session,
    run_id: str,
    candidate_names: list[str],
    *,
    max_chunk_id: int | None = None,
    chunk_start_id: int | None = None,
    chunk_end_id: int | None = None,
    max_rows_per_candidate: int = 3,
) -> dict[str, str]:
    """
    创建时间: 2026-05-02
    任务: fix-graph-projection-relations
    新建原因: slot 候选不会直接命中文本检索，必须补一层“surface + chunk + 关系证据 + 原文”
              的可读上下文，模型才能在保留 slot key 的同时判断引用去向。
    """
    candidate_set = {normalize_reference_name(name) for name in candidate_names if normalize_reference_name(name)}
    if not candidate_set:
        return {}

    stmt = (
        select(ChunkRelation, Chunk.text)
        .join(Chunk, (Chunk.chunk_id == ChunkRelation.chunk_id) & (Chunk.run_id == ChunkRelation.run_id))
        .where(ChunkRelation.run_id == run_id)
        .order_by(ChunkRelation.chunk_id, ChunkRelation.id)
    )
    if max_chunk_id is not None:
        stmt = stmt.where(ChunkRelation.chunk_id <= max_chunk_id)
    if chunk_start_id is not None:
        stmt = stmt.where(ChunkRelation.chunk_id >= chunk_start_id)
    if chunk_end_id is not None:
        stmt = stmt.where(ChunkRelation.chunk_id <= chunk_end_id)

    result = session.execute(stmt).all()
    contexts: dict[str, list[str]] = {name: [] for name in candidate_set}
    for relation_row, chunk_text in result:
        endpoints = (
            (
                _resolve_relation_reference_candidate_name(
                    relation_row.from_char,
                    chunk_id=relation_row.chunk_id,
                    resolved_global_name=relation_row.resolved_from_global_name,
                ),
                relation_row.from_char,
                relation_row.to_char,
                "from",
            ),
            (
                _resolve_relation_reference_candidate_name(
                    relation_row.to_char,
                    chunk_id=relation_row.chunk_id,
                    resolved_global_name=relation_row.resolved_to_global_name,
                ),
                relation_row.to_char,
                relation_row.from_char,
                "to",
            ),
        )
        for candidate_name, endpoint_name, counterpart_name, direction in endpoints:
            if candidate_name not in candidate_set:
                continue
            rows = contexts[candidate_name]
            if len(rows) >= max_rows_per_candidate:
                continue
            surface_name = extract_surface_name_from_reference_slot(candidate_name) or normalize_reference_name(
                endpoint_name
            )
            chunk_excerpt = normalize_reference_name(chunk_text)
            if len(chunk_excerpt) > 120:
                chunk_excerpt = f"{chunk_excerpt[:117]}..."
            relation_evidence = normalize_reference_name(relation_row.evidence)
            relation_type = normalize_reference_name(relation_row.type)
            parts = [
                f"chunk {relation_row.chunk_id}",
                f"原文称呼：{surface_name}",
                f"关系端点：{normalize_reference_name(endpoint_name)} ({direction})",
                f"对端：{normalize_reference_name(counterpart_name)}",
            ]
            if relation_type:
                parts.append(f"关系类型：{relation_type}")
            if relation_evidence:
                parts.append(f"关系证据：{relation_evidence}")
            if chunk_excerpt:
                parts.append(f"分块原文：{chunk_excerpt}")
            rows.append("；".join(parts))

    return {name: " | ".join(rows) for name, rows in contexts.items() if rows}


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
              不能因为行上残留旧实名就继续被 graph/results 误消费；同时 Phase4 relation
              端点可能直接落 slot 名，这里也要能回退命中 surface-keyed resolution map。
    """
    normalized_surface = normalize_reference_name(surface_name)
    resolved_global_name = existing_resolved_global_name
    if normalized_surface and is_reference_surface_name(normalized_surface):
        # reference surface 只能相信当前 checkpoint 的解析结果；
        # 如果本轮 map 里已经没有它，说明它已被降级回 unresolved，旧 resolved 值必须清空。
        resolved_global_name = None
        for lookup_key in build_reference_resolution_lookup_keys(normalized_surface):
            candidate_name = normalize_reference_name(reference_resolutions.get(lookup_key))
            if candidate_name:
                resolved_global_name = candidate_name
                break
    return decide_character_reference(
        normalized_surface,
        resolved_global_name=resolved_global_name,
        chunk_id=chunk_id,
    )


def _build_history_window_stmt(
    model: type[Any],
    *,
    run_id: str,
    from_chunk: int | None,
    to_chunk: int | None,
):
    """
    创建时间: 2026-05-02
    任务: fix-graph-projection-relations
    新建原因: 关系历史回刷现在既要支持全量三表同步，也要支持 projection 前的窗口级
              relation-only 回刷，这里统一收口 run/chunk 窗口过滤，避免三处重复拼接条件。
    """
    stmt = select(model).where(model.run_id == run_id)
    if from_chunk is not None:
        stmt = stmt.where(model.chunk_id >= from_chunk)
    if to_chunk is not None:
        stmt = stmt.where(model.chunk_id <= to_chunk)
    return stmt


def _normalize_history_table_scopes(table_scopes: tuple[str, ...] | list[str] | set[str] | None) -> tuple[str, ...]:
    """
    创建时间: 2026-05-02
    任务: fix-graph-projection-relations
    新建原因: 历史回刷需要允许调用方只处理 relations，必须先统一校验 table_scopes，
              避免拼错 scope 名时静默降级成“什么都没刷”。
    """
    if table_scopes is None:
        return tuple(sorted(HISTORY_TABLE_SCOPES))
    normalized_scopes = tuple(dict.fromkeys(str(scope).strip() for scope in table_scopes if str(scope).strip()))
    invalid_scopes = sorted(set(normalized_scopes) - HISTORY_TABLE_SCOPES)
    if invalid_scopes:
        raise ValueError(f"invalid history table scopes: {', '.join(invalid_scopes)}")
    return normalized_scopes


def apply_reference_resolutions_to_history(
    session: Session,
    run_id: str,
    reference_resolutions: dict[str, str],
    *,
    apply: bool = True,
    from_chunk: int | None = None,
    to_chunk: int | None = None,
    table_scopes: tuple[str, ...] | list[str] | set[str] | None = None,
) -> dict[str, int]:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: reference_resolutions 不能只停留在 checkpoint；需要同步驱动 chunk_* 历史行的 resolved 字段消费。
    修改时间: 2026-05-02
    修改原因: 支持 projection 前只回刷当前窗口的 chunk_relations，解决 checkpoint
              已有 resolution 但关系历史行晚写入后长期 stale 的问题。

    Returns:
        受处理的历史行统计，key 为表类型。
    """
    scopes = set(_normalize_history_table_scopes(table_scopes))
    counts = {
        "chunk_characters": 0,
        "chunk_dialogues": 0,
        "chunk_relations": 0,
    }

    if "chunk_characters" in scopes:
        chunk_characters: list[ChunkCharacter] = list(
            session.execute(
                _build_history_window_stmt(
                    ChunkCharacter,
                    run_id=run_id,
                    from_chunk=from_chunk,
                    to_chunk=to_chunk,
                )
            )
            .scalars()
            .all()
        )
        counts["chunk_characters"] = len(chunk_characters)
        for character_row in chunk_characters:
            decision = _resolve_history_reference_decision(
                character_row.surface_name or character_row.name,
                chunk_id=character_row.chunk_id,
                reference_resolutions=reference_resolutions,
                existing_resolved_global_name=character_row.resolved_global_name,
            )
            if apply:
                character_row.surface_name = decision.surface_name
                character_row.reference_kind = decision.reference_kind
                character_row.reference_slot = decision.reference_slot
                character_row.resolved_global_name = decision.resolved_global_name
                character_row.global_skip_reason = decision.global_skip_reason

    if "chunk_dialogues" in scopes:
        chunk_dialogues: list[ChunkDialogue] = list(
            session.execute(
                _build_history_window_stmt(
                    ChunkDialogue,
                    run_id=run_id,
                    from_chunk=from_chunk,
                    to_chunk=to_chunk,
                )
            )
            .scalars()
            .all()
        )
        counts["chunk_dialogues"] = len(chunk_dialogues)
        for dialogue_row in chunk_dialogues:
            existing_by_surface: dict[str, dict[str, object]] = {}
            for item in dialogue_row.speaker_references or []:
                if isinstance(item, dict) and isinstance(item.get("surface_name"), str):
                    existing_by_surface[str(item["surface_name"])] = item

            rebuilt_references: list[dict[str, object]] = []
            for speaker_name in dialogue_row.speaker or []:
                if not speaker_name:
                    continue
                existing_reference = existing_by_surface.get(str(speaker_name))
                existing_resolved_global_name = None
                if existing_reference is not None and isinstance(existing_reference.get("resolved_global_name"), str):
                    existing_resolved_global_name = str(existing_reference["resolved_global_name"])
                decision = _resolve_history_reference_decision(
                    speaker_name,
                    chunk_id=dialogue_row.chunk_id,
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
                dialogue_row.speaker_references = rebuilt_references or None

    if "chunk_relations" in scopes:
        chunk_relations: list[ChunkRelation] = list(
            session.execute(
                _build_history_window_stmt(
                    ChunkRelation,
                    run_id=run_id,
                    from_chunk=from_chunk,
                    to_chunk=to_chunk,
                )
            )
            .scalars()
            .all()
        )
        counts["chunk_relations"] = len(chunk_relations)
        for relation_row in chunk_relations:
            from_decision = _resolve_history_reference_decision(
                relation_row.from_char,
                chunk_id=relation_row.chunk_id,
                reference_resolutions=reference_resolutions,
                existing_resolved_global_name=relation_row.resolved_from_global_name,
            )
            to_decision = _resolve_history_reference_decision(
                relation_row.to_char,
                chunk_id=relation_row.chunk_id,
                reference_resolutions=reference_resolutions,
                existing_resolved_global_name=relation_row.resolved_to_global_name,
            )
            reasons = [
                f"{decision.surface_name}: {decision.global_skip_reason}"
                for decision in (from_decision, to_decision)
                if not decision.can_enter_global_character and decision.global_skip_reason
            ]
            if apply:
                relation_row.from_reference_kind = from_decision.reference_kind
                relation_row.to_reference_kind = to_decision.reference_kind
                relation_row.resolved_from_global_name = from_decision.resolved_global_name
                relation_row.resolved_to_global_name = to_decision.resolved_global_name
                relation_row.reference_skip_reason = "; ".join(reasons) if reasons else None

    return counts


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
