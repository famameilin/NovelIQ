from __future__ import annotations

from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import text

from src.agents.annotation.memory import IdentityMemory, load_identity_memory
from src.config import settings
from src.config.constants.annotation import (
    SYMMETRIC_RELATION_TYPES,
    VALID_CHANGE_TYPES,
    VALID_RELATION_TYPES,
)
from src.models.local.character_reference_policy import decide_character_reference, is_reference_surface_name
from src.storage.models import ChunkCharacter, ChunkDialogue, ChunkRelation
from src.storage.repositories import AnnotationRepository, GraphRepository, RunRepository

PENDING_RETRY_LIMIT = 200
HIERARCHICAL_SYMMETRIC_RELATION_TYPES = frozenset({"spouse_of", "sibling_of"})
REFERENCE_ENDPOINT_KINDS = frozenset({"pov_slot", "pronoun", "generic_reference"})
BENIGN_UNRESOLVED_REFERENCE_ERROR = "unresolved reference endpoint"


def _resolve_name(
    raw_name: str | None,
    alias_map: dict[str, str],
    graph_aliases: dict[str, str],
    *,
    resolved_global_name: str | None = None,
) -> str | None:
    """
    修改时间: 2026-04-29
    任务: 角色引用分层重构
    修改原因: graph projection 只能接收已通过 global-character 准入的名字，未解析代词不能被别名表误提升。
    """
    if raw_name is None and resolved_global_name is None:
        return None
    name = raw_name.strip() if raw_name else ""
    explicit_name = resolved_global_name.strip() if resolved_global_name else None
    if not name and not explicit_name:
        return None
    merged_aliases = {**graph_aliases, **alias_map}
    decision = decide_character_reference(
        name or explicit_name,
        alias_map=merged_aliases,
        resolved_global_name=explicit_name,
    )
    return decision.resolved_global_name if decision.can_enter_global_character else None


def _should_record_alias(surface_name: str | None, resolved_name: str) -> bool:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: 已解析代词可以投影为实名节点，但 raw 代词不能写入 graph_aliases 形成全局别名。
    """
    if surface_name is None:
        return False
    normalized = surface_name.strip()
    return bool(normalized) and normalized != resolved_name and not is_reference_surface_name(normalized)


def _fetch_pending_relations(
    session,
    run_id: str,
    to_chunk: int | None,
    limit: int = PENDING_RETRY_LIMIT,
) -> list[ChunkRelation]:
    """
    修改时间: 2026-04-29
    任务: 角色引用分层重构
    修改原因: pending retry 会重新处理未解析端点，必须保留显式 projection_error 供诊断和重投影观察。
    """
    query = (
        session.query(ChunkRelation)
        .filter(ChunkRelation.run_id == run_id)
        .filter(ChunkRelation.projection_status == "pending")
    )
    if to_chunk is not None:
        query = query.filter(ChunkRelation.chunk_id <= to_chunk)
    return list(query.order_by(ChunkRelation.chunk_id, ChunkRelation.id).limit(limit).all())


def _merge_relations_for_projection(
    window_relations: list[ChunkRelation],
    retry_relations: list[ChunkRelation],
) -> list[ChunkRelation]:
    """
    修改时间: 2026-04-29
    任务: 角色引用分层重构
    修改原因: 合并窗口关系与 retry 关系时继续按 row id 去重，避免同一 pending 端点被重复计数。
    """
    seen: set[int] = set()
    merged: list[ChunkRelation] = []
    for relation in [*window_relations, *retry_relations]:
        if relation.id is None or relation.id in seen:
            continue
        seen.add(relation.id)
        merged.append(relation)
    return merged


def _get_last_projected_chunk(session, run_id: str) -> int:
    """
    修改时间: 2026-04-29
    任务: 角色引用分层重构
    修改原因: 增量投影继续以已完成关系为边界，pending 的未解析引用必须留待后续重试。
    """
    result = session.execute(
        text("""
            SELECT COALESCE(MAX(chunk_id), -1) AS max_chunk_id
            FROM chunk_relations
            WHERE run_id = :run_id AND projection_status = 'projected'
        """),
        {"run_id": run_id},
    ).fetchone()
    return result.max_chunk_id if result else -1


def _backfill_relation_history_before_projection(
    session,
    *,
    run_id: str,
    state: IdentityMemory,
    from_chunk: int,
    to_chunk: int | None,
    retry_relations: list[ChunkRelation],
) -> dict[str, int]:
    """
    创建时间: 2026-05-02
    任务: fix-graph-projection-relations
    新建原因: graph projection 除了消费当前窗口，还会重试更早的 pending relation；
              投影前必须先用最新 checkpoint 回刷这些 relation 行，避免 stale resolved 字段
              让本来可投影或应终态化的引用关系继续卡在旧状态。
    """
    backfill_from_chunk = from_chunk
    if retry_relations:
        earliest_retry_chunk = min(relation.chunk_id for relation in retry_relations)
        backfill_from_chunk = min(backfill_from_chunk, earliest_retry_chunk)
    report = AnnotationRepository(session).apply_reference_resolutions_to_history(
        run_id,
        _build_reference_resolutions_from_memory(state),
        apply=True,
        from_chunk=backfill_from_chunk,
        to_chunk=to_chunk,
        table_scopes=("chunk_relations",),
    )
    session.flush()
    logger.debug(
        "relation history backfill before projection: run_id={} from_chunk={} to_chunk={} report={}",
        run_id,
        backfill_from_chunk,
        to_chunk,
        report,
    )
    return report


def _build_reference_resolutions_from_memory(state: IdentityMemory) -> dict[str, str]:
    """
    从 agent 身份记忆构建引用解析映射：
    别名表（表面称呼 → 规范名）即为引用解析的权威来源，
    规范名自身映射到自身，保证已解析实名的引用行不被误清空
    """
    resolutions = {name: name for name in state.known_canonical_names}
    resolutions.update(state.alias_map)
    return resolutions


def _is_reference_endpoint(raw_name: str | None, reference_kind: str | None) -> bool:
    """
    创建时间: 2026-05-02
    任务: fix-graph-projection-relations
    新建原因: unresolved 端点里只有“局部引用位”应该转成 benign failed；
              这里统一识别 slot/pronoun/generic_reference，避免把普通实名也误终态化。
    """
    return (reference_kind or "").strip() in REFERENCE_ENDPOINT_KINDS or is_reference_surface_name(raw_name)


def _should_fail_unresolved_reference_endpoint(
    relation: ChunkRelation,
    *,
    resolved_from: str | None,
    resolved_to: str | None,
) -> bool:
    """
    创建时间: 2026-05-02
    任务: fix-graph-projection-relations
    新建原因: 只有“剩下没解开的都是引用端点”时，关系才能安全终态化为 benign failed；
              如果还夹杂未解析实名，就必须继续 pending，等待后续角色主链补齐。
    """
    unresolved_reference_endpoint = False
    unresolved_non_reference_endpoint = False

    if resolved_from is None:
        if _is_reference_endpoint(relation.from_char, relation.from_reference_kind):
            unresolved_reference_endpoint = True
        else:
            unresolved_non_reference_endpoint = True

    if resolved_to is None:
        if _is_reference_endpoint(relation.to_char, relation.to_reference_kind):
            unresolved_reference_endpoint = True
        else:
            unresolved_non_reference_endpoint = True

    return unresolved_reference_endpoint and not unresolved_non_reference_endpoint


def project_graph_tables(
    run_id: str,
    from_chunk: int | None = None,
    to_chunk: int | None = None,
    session=None,
    rebuild: bool = False,
) -> None:
    """
    2026-04-27，任务：timeline-contract-graph-projection
    - “无变化”关系不再写入 graph history
    - 若某条已投影关系后来被修正为“无变化”，必须删除旧事件并回刷受影响 pair
    2026-04-30，任务：storage-api-graph-mypy-cleanup
    - relation 端点原始别名在写入 alias 表前先做显式空值收窄，保持 None 不进入 graph alias 主链
    """
    if session is None:
        raise ValueError("session is required for project_graph_tables")

    run_repo = RunRepository(session)
    if run_repo.get_run(run_id) is None:
        raise ValueError(f"run not found: {run_id}")

    graph_repo = GraphRepository(session)
    state: IdentityMemory = load_identity_memory(session, run_id)
    if rebuild:
        logger.info("graph projection rebuild requested run_id={} to_chunk={}", run_id, to_chunk)
        graph_repo.reset_graph_tables(run_id)
        from_chunk = 0
    elif from_chunk is None:
        from_chunk = _get_last_projected_chunk(session, run_id) + 1

    retry_relations = _fetch_pending_relations(session, run_id, to_chunk=to_chunk)
    _backfill_relation_history_before_projection(
        session,
        run_id=run_id,
        state=state,
        from_chunk=from_chunk,
        to_chunk=to_chunk,
        retry_relations=retry_relations,
    )

    chunk_characters = list(
        (
            session.query(ChunkCharacter)
            .filter(ChunkCharacter.run_id == run_id)
            .filter(ChunkCharacter.chunk_id >= from_chunk)
            .filter(ChunkCharacter.chunk_id <= to_chunk)
            if to_chunk is not None
            else session.query(ChunkCharacter)
            .filter(ChunkCharacter.run_id == run_id)
            .filter(ChunkCharacter.chunk_id >= from_chunk)
        )
        .order_by(ChunkCharacter.chunk_id, ChunkCharacter.id)
        .all()
    )
    chunk_dialogues = list(
        (
            session.query(ChunkDialogue)
            .filter(ChunkDialogue.run_id == run_id)
            .filter(ChunkDialogue.chunk_id >= from_chunk)
            .filter(ChunkDialogue.chunk_id <= to_chunk)
            if to_chunk is not None
            else session.query(ChunkDialogue)
            .filter(ChunkDialogue.run_id == run_id)
            .filter(ChunkDialogue.chunk_id >= from_chunk)
        )
        .order_by(ChunkDialogue.chunk_id, ChunkDialogue.id)
        .all()
    )
    window_relations = list(
        (
            session.query(ChunkRelation)
            .filter(ChunkRelation.run_id == run_id)
            .filter(ChunkRelation.chunk_id >= from_chunk)
            .filter(ChunkRelation.chunk_id <= to_chunk)
            if to_chunk is not None
            else session.query(ChunkRelation)
            .filter(ChunkRelation.run_id == run_id)
            .filter(ChunkRelation.chunk_id >= from_chunk)
        )
        .order_by(ChunkRelation.chunk_id, ChunkRelation.id)
        .all()
    )
    chunk_relations = _merge_relations_for_projection(window_relations, retry_relations)

    alias_map = dict(state.alias_map)
    graph_alias_map = graph_repo.fetch_alias_map(run_id)

    # P1.1 修复：批量加载已有实体类型，避免把类型硬编码成 "character"
    existing_entities = graph_repo.fetch_entities(run_id)
    existing_types: dict[str, str] = {e.canonical_name: e.entity_type for e in existing_entities if e.canonical_name}
    # 合并 agent 身份记忆给出的 entity_types，让 LLM 判定的类型能流入图谱投影
    if state.entity_types:
        existing_types.update(state.entity_types)

    for row in chunk_characters:
        surface_name = row.surface_name or row.name
        resolved_name = _resolve_name(
            surface_name,
            alias_map,
            graph_alias_map,
            resolved_global_name=row.resolved_global_name,
        )
        if resolved_name is None:
            continue
        entity = graph_repo.upsert_entity(
            run_id=run_id,
            canonical_name=resolved_name,
            entity_type=existing_types.get(resolved_name, "character"),
            first_seen_chunk=row.chunk_id,
            last_seen_chunk=row.chunk_id,
            primary_role_function=row.role_function,
            last_emotion_score=row.emotion_score,
            last_action=row.action,
            source_confidence=1.0,
        )
        if entity.entity_id is None:
            continue
        graph_repo.upsert_alias(
            run_id=run_id,
            entity_id=entity.entity_id,
            alias=resolved_name,
            source_chunk_id=row.chunk_id,
            evidence=row.action,
            confidence=1.0,
            source_type="chunk_character",
            is_primary=True,
        )
        graph_alias_map[resolved_name] = resolved_name
        if _should_record_alias(surface_name, resolved_name):
            graph_repo.upsert_alias(
                run_id=run_id,
                entity_id=entity.entity_id,
                alias=surface_name,
                source_chunk_id=row.chunk_id,
                evidence=row.action,
                confidence=0.9,
                source_type="disambiguation",
                is_primary=False,
            )
            graph_alias_map[surface_name] = resolved_name

    for row in chunk_dialogues:
        speakers = row.speaker or []
        if not speakers:
            continue
        speaker_reference_by_surface: dict[str, str | None] = {}
        for item in row.speaker_references or []:
            if not isinstance(item, dict):
                continue
            surface_name = str(item.get("surface_name") or "").strip()
            if surface_name:
                speaker_reference_by_surface[surface_name] = (
                    str(item.get("resolved_global_name")).strip()
                    if item.get("resolved_global_name") is not None
                    else None
                )
        for speaker_name in speakers:
            if not speaker_name:
                continue
            resolved_name = _resolve_name(
                speaker_name,
                alias_map,
                graph_alias_map,
                resolved_global_name=speaker_reference_by_surface.get(speaker_name),
            )
            if resolved_name is None:
                continue
            entity = graph_repo.upsert_entity(
                run_id=run_id,
                canonical_name=resolved_name,
                entity_type=existing_types.get(resolved_name, "character"),
                first_seen_chunk=row.chunk_id,
                last_seen_chunk=row.chunk_id,
                source_confidence=0.8,
            )
            if entity.entity_id is None:
                continue
            graph_repo.upsert_alias(
                run_id=run_id,
                entity_id=entity.entity_id,
                alias=resolved_name,
                source_chunk_id=row.chunk_id,
                evidence=row.content,
                confidence=0.8,
                source_type="dialogue",
                is_primary=True,
            )
            graph_alias_map[resolved_name] = resolved_name
            if _should_record_alias(speaker_name, resolved_name):
                graph_repo.upsert_alias(
                    run_id=run_id,
                    entity_id=entity.entity_id,
                    alias=speaker_name,
                    source_chunk_id=row.chunk_id,
                    evidence=row.content,
                    confidence=0.8,
                    source_type="dialogue",
                    is_primary=False,
                )
                graph_alias_map[speaker_name] = resolved_name

    projected_count = 0
    pending_count = 0
    failed_count = 0
    no_change_count = 0
    affected_pairs: set[tuple[int, int]] = set()
    allowed_relation_types = VALID_RELATION_TYPES | set(settings.analysis.valid_hierarchical_relation_types)

    for relation in chunk_relations:
        resolved_from = _resolve_name(
            relation.from_char,
            alias_map,
            graph_alias_map,
            resolved_global_name=relation.resolved_from_global_name,
        )
        resolved_to = _resolve_name(
            relation.to_char,
            alias_map,
            graph_alias_map,
            resolved_global_name=relation.resolved_to_global_name,
        )
        if resolved_from is None or resolved_to is None:
            relation.projected_at = None
            if _should_fail_unresolved_reference_endpoint(
                relation,
                resolved_from=resolved_from,
                resolved_to=resolved_to,
            ):
                relation.projection_status = "failed"
                relation.projection_error = BENIGN_UNRESOLVED_REFERENCE_ERROR
                failed_count += 1
            else:
                relation.projection_status = "pending"
                relation.projection_error = "unresolved global-character endpoint"
                pending_count += 1
            continue
        if resolved_from == resolved_to:
            relation.projection_status = "failed"
            relation.projection_error = "self relation"
            relation.projected_at = None
            failed_count += 1
            continue

        from_entity = graph_repo.upsert_entity(
            run_id=run_id,
            canonical_name=resolved_from,
            entity_type=existing_types.get(resolved_from, "character"),
            first_seen_chunk=relation.chunk_id,
            last_seen_chunk=relation.chunk_id,
            source_confidence=relation.confidence,
        )
        to_entity = graph_repo.upsert_entity(
            run_id=run_id,
            canonical_name=resolved_to,
            entity_type=existing_types.get(resolved_to, "character"),
            first_seen_chunk=relation.chunk_id,
            last_seen_chunk=relation.chunk_id,
            source_confidence=relation.confidence,
        )
        if from_entity.entity_id is None or to_entity.entity_id is None:
            relation.projection_status = "failed"
            relation.projection_error = "entity upsert failed"
            relation.projected_at = None
            failed_count += 1
            continue

        graph_repo.upsert_alias(
            run_id=run_id,
            entity_id=from_entity.entity_id,
            alias=resolved_from,
            source_chunk_id=relation.chunk_id,
            evidence=relation.evidence,
            confidence=relation.confidence,
            source_type="relation_projection",
            is_primary=relation.from_char == resolved_from,
        )
        graph_alias_map[resolved_from] = resolved_from
        from_alias = relation.from_char
        if from_alias is not None and _should_record_alias(from_alias, resolved_from):
            graph_repo.upsert_alias(
                run_id=run_id,
                entity_id=from_entity.entity_id,
                alias=from_alias,
                source_chunk_id=relation.chunk_id,
                evidence=relation.evidence,
                confidence=relation.confidence,
                source_type="relation_projection",
                is_primary=False,
            )
            graph_alias_map[from_alias] = resolved_from

        graph_repo.upsert_alias(
            run_id=run_id,
            entity_id=to_entity.entity_id,
            alias=resolved_to,
            source_chunk_id=relation.chunk_id,
            evidence=relation.evidence,
            confidence=relation.confidence,
            source_type="relation_projection",
            is_primary=relation.to_char == resolved_to,
        )
        graph_alias_map[resolved_to] = resolved_to
        to_alias = relation.to_char
        if to_alias is not None and _should_record_alias(to_alias, resolved_to):
            graph_repo.upsert_alias(
                run_id=run_id,
                entity_id=to_entity.entity_id,
                alias=to_alias,
                source_chunk_id=relation.chunk_id,
                evidence=relation.evidence,
                confidence=relation.confidence,
                source_type="relation_projection",
                is_primary=False,
            )
            graph_alias_map[to_alias] = resolved_to

        rel_type = relation.type or "未知"
        rel_change = (relation.change or "").strip()

        # 写入图谱前先校验 relation_type 和 change_type
        if rel_type not in allowed_relation_types:
            logger.warning(
                "Skipping relation with invalid type '{}' (chunk={})",
                rel_type,
                relation.chunk_id,
            )
            relation.projection_status = "pending"
            relation.projection_error = f"invalid relation_type: {rel_type}"
            relation.projected_at = None
            pending_count += 1
            continue
        if rel_change in {"", "无变化"}:
            if relation.id is not None:
                deleted_pair = graph_repo.delete_relation_event_by_source_row_id(run_id, relation.id)
                if deleted_pair is not None:
                    affected_pairs.add(deleted_pair)
            relation.projection_status = "projected"
            relation.projected_at = datetime.now(UTC)
            relation.projection_error = None
            no_change_count += 1
            continue
        if rel_change not in VALID_CHANGE_TYPES:
            logger.warning(
                "Skipping relation with invalid change '{}' (chunk={})",
                rel_change,
                relation.chunk_id,
            )
            relation.projection_status = "pending"
            relation.projection_error = f"invalid change_type: {rel_change}"
            relation.projected_at = None
            pending_count += 1
            continue

        event = graph_repo.insert_relation_event(
            run_id=run_id,
            from_entity_id=from_entity.entity_id,
            to_entity_id=to_entity.entity_id,
            relation_type=rel_type,
            change_type=rel_change,
            chunk_id=relation.chunk_id,
            evidence=relation.evidence,
            confidence=relation.confidence,
            source_relation_row_id=relation.id,
            directionality=(
                "symmetric"
                if rel_type in (SYMMETRIC_RELATION_TYPES | HIERARCHICAL_SYMMETRIC_RELATION_TYPES)
                else "directed"
            ),
        )
        if event is None:
            relation.projection_status = "failed"
            relation.projection_error = "event insert failed"
            relation.projected_at = None
            failed_count += 1
            continue

        affected_pairs.add((from_entity.entity_id, to_entity.entity_id))
        relation.projection_status = "projected"
        relation.projected_at = datetime.now(UTC)
        relation.projection_error = None
        projected_count += 1

    graph_repo.refresh_relation_projections(run_id, affected_pairs)

    # 全投影作为一个事务原子提交：backfill + 窗口内 projection 共享同一个 commit，
    # 任意子步骤失败会整体回滚，避免半完成状态污染 projected 标记。
    session.commit()
    logger.info(
        "graph projection completed: "
        "run_id={} from_chunk={} to_chunk={} rebuild={} "
        "window_relations={} retried_pending={} total_relations={} "
        "projected={} pending={} failed={} no_change_skipped={} affected_pairs={}",
        run_id,
        from_chunk,
        to_chunk,
        rebuild,
        len(window_relations),
        max(0, len(chunk_relations) - len(window_relations)),
        len(chunk_relations),
        projected_count,
        pending_count,
        failed_count,
        no_change_count,
        len(affected_pairs),
    )
