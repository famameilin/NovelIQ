from __future__ import annotations

from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import text

from src.config import settings
from src.config.constants.annotation import (
    SYMMETRIC_RELATION_TYPES,
    VALID_CHANGE_TYPES,
    VALID_RELATION_TYPES,
)
from src.models.local.disambiguation import DisambiguationState
from src.storage.models import ChunkCharacter, ChunkDialogue, ChunkRelation
from src.storage.repositories import GraphRepository, RunRepository
from src.workflows.annotate_helpers.disambiguation.checkpoint import (
    _load_disambig_checkpoint,
)

PENDING_RETRY_LIMIT = 200
HIERARCHICAL_SYMMETRIC_RELATION_TYPES = frozenset({"spouse_of", "sibling_of"})


def _resolve_name(raw_name: str | None, alias_map: dict[str, str], graph_aliases: dict[str, str]) -> str | None:
    if raw_name is None:
        return None
    name = raw_name.strip()
    if not name:
        return None
    return alias_map.get(name) or graph_aliases.get(name) or name


def _fetch_pending_relations(
    session,
    run_id: str,
    to_chunk: int | None,
    limit: int = PENDING_RETRY_LIMIT,
) -> list[ChunkRelation]:
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
    seen: set[int] = set()
    merged: list[ChunkRelation] = []
    for relation in [*window_relations, *retry_relations]:
        if relation.id is None or relation.id in seen:
            continue
        seen.add(relation.id)
        merged.append(relation)
    return merged


def _get_last_projected_chunk(session, run_id: str) -> int:
    """查询 ChunkRelation 表中已投影的最大 chunk_id。"""
    result = session.execute(
        text("""
            SELECT COALESCE(MAX(chunk_id), -1) AS max_chunk_id
            FROM chunk_relations
            WHERE run_id = :run_id AND projection_status = 'projected'
        """),
        {"run_id": run_id},
    ).fetchone()
    return result._mapping["max_chunk_id"] if result else -1


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
    """
    if session is None:
        raise ValueError("session is required for project_graph_tables")

    run_repo = RunRepository(session)
    if run_repo.get_run(run_id) is None:
        raise ValueError(f"run not found: {run_id}")

    graph_repo = GraphRepository(session)
    state: DisambiguationState = _load_disambig_checkpoint(session, run_id)
    if rebuild:
        logger.info("graph projection rebuild requested run_id={} to_chunk={}", run_id, to_chunk)
        graph_repo.reset_graph_tables(run_id)
        from_chunk = 0
    elif from_chunk is None:
        from_chunk = _get_last_projected_chunk(session, run_id) + 1

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
    retry_relations = _fetch_pending_relations(session, run_id, to_chunk=to_chunk)
    chunk_relations = _merge_relations_for_projection(window_relations, retry_relations)

    alias_map = state.get_alias_merges_dict()
    graph_alias_map = graph_repo.fetch_alias_map(run_id)

    # P1.1 fix: batch-load existing entity types to avoid hardcoded "character"
    existing_entities = graph_repo.fetch_entities(run_id)
    existing_types: dict[str, str] = {e.canonical_name: e.entity_type for e in existing_entities if e.canonical_name}
    # Merge disambiguation entity_types so LLM-judged types flow into graph projection
    if state.entity_types:
        existing_types.update(state.get_entity_types_dict())

    # Build set of uncertain names: review/low status, not in alias_merges or known_canonicals
    review_dict = state.get_review_status_dict()
    uncertain_names: set[str] = set()
    canonical_names = state.known_canonical_names
    alias_set = {a for a, _ in state.alias_merges}
    for name, review in review_dict.items():
        if (
            review.status != "resolved"
            and review.confidence in ("low", "medium")
            and name not in canonical_names
            and name not in alias_set
        ):
            uncertain_names.add(name)
            logger.debug(
                "Uncertain name skipped: '{}' (status={}, confidence={})",
                name,
                review.status,
                review.confidence,
            )

    if uncertain_names:
        logger.info(
            "Skipping {} uncertain names from graph projection: {}",
            len(uncertain_names),
            uncertain_names,
        )

    for row in chunk_characters:
        resolved_name = _resolve_name(row.name, alias_map, graph_alias_map)
        if resolved_name is None:
            continue
        if resolved_name in uncertain_names:
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
        if row.name and row.name != resolved_name:
            graph_repo.upsert_alias(
                run_id=run_id,
                entity_id=entity.entity_id,
                alias=row.name,
                source_chunk_id=row.chunk_id,
                evidence=row.action,
                confidence=0.9,
                source_type="disambiguation",
                is_primary=False,
            )
            graph_alias_map[row.name] = resolved_name

    for row in chunk_dialogues:
        speakers = row.speaker or []
        if not speakers:
            continue
        for speaker_name in speakers:
            if not speaker_name:
                continue
            resolved_name = _resolve_name(speaker_name, alias_map, graph_alias_map)
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
            if speaker_name != resolved_name:
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
        resolved_from = _resolve_name(relation.from_char, alias_map, graph_alias_map)
        resolved_to = _resolve_name(relation.to_char, alias_map, graph_alias_map)
        if resolved_from is None or resolved_to is None:
            relation.projection_status = "pending"
            relation.projection_error = "unresolved endpoint"
            relation.projected_at = None
            pending_count += 1
            continue
        if resolved_from == resolved_to:
            relation.projection_status = "failed"
            relation.projection_error = "self relation"
            relation.projected_at = None
            failed_count += 1
            continue
        # P4: Filter uncertain endpoints from relation projection
        if resolved_from in uncertain_names or resolved_to in uncertain_names:
            relation.projection_status = "pending"
            relation.projection_error = "uncertain endpoint"
            relation.projected_at = None
            pending_count += 1
            logger.debug(
                "Skipping relation with uncertain endpoint: '{}' or '{}'",
                resolved_from,
                resolved_to,
            )
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
        if relation.from_char and relation.from_char != resolved_from:
            graph_repo.upsert_alias(
                run_id=run_id,
                entity_id=from_entity.entity_id,
                alias=relation.from_char,
                source_chunk_id=relation.chunk_id,
                evidence=relation.evidence,
                confidence=relation.confidence,
                source_type="relation_projection",
                is_primary=False,
            )
            graph_alias_map[relation.from_char] = resolved_from

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
        if relation.to_char and relation.to_char != resolved_to:
            graph_repo.upsert_alias(
                run_id=run_id,
                entity_id=to_entity.entity_id,
                alias=relation.to_char,
                source_chunk_id=relation.chunk_id,
                evidence=relation.evidence,
                confidence=relation.confidence,
                source_type="relation_projection",
                is_primary=False,
            )
            graph_alias_map[relation.to_char] = resolved_to

        rel_type = relation.type or "未知"
        rel_change = (relation.change or "").strip()

        # Validate relation_type and change_type before writing to graph
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
