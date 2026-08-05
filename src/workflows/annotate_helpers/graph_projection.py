"""
章节正式标注与连续性事实的数据库图投影
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.storage.models import (
    ChapterAnnotationRecord,
    ContinuityFact,
    GraphEntity,
    GraphEntityAlias,
    GraphEntityParticipant,
    GraphFact,
    GraphFactSource,
    GraphFactVersion,
    GraphRelationCurrent,
    GraphRelationEvent,
)

_CONFIDENCE_SCORE = {"high": 0.9, "medium": 0.7, "low": 0.5}
_CHANGE_LABEL = {
    "assert": "新建",
    "reinforce": "强化",
    "refine": "强化",
    "supersede": "强化",
    "weaken": "弱化",
    "break": "断裂",
    "retract": "断裂",
}


def stable_annotation_fact_id(annotation_id: str, payload_path: str) -> str:
    """2026-08-05 用于按 annotation_id 与 payload 路径生成可重建的稳定来源事实 ID"""
    digest = hashlib.sha256(f"{annotation_id}:{payload_path}".encode()).hexdigest()
    return f"ann_{digest}"


def _segment_fact(
    *,
    chapter_id: int,
    item: dict[str, Any],
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """2026-08-05 用于把章节 segment 转换为可查询的图事实语义"""
    content = {
        "kind": "segment",
        "chunk_id": item["chunk_id"],
        "summary": item["summary"],
        "emotional_valence": item["emotional_valence"],
        "event_type": item["event_type"],
        "pivot_moment": item["pivot_moment"],
        "cliffhanger": item["cliffhanger"],
    }
    fact: dict[str, Any] = {
        "fact_type": "chapter_segment",
        "subject": {"name": f"chapter:{chapter_id}", "entity_type": "chapter"},
        "predicate": "contains_segment",
        "object": None,
        "value": content,
        "participants": [],
        "scope": f"chapter:{chapter_id}",
        "story_time": None,
        "assertion": "affirmed",
        "confidence": "high",
        "content": content,
    }
    evidence = {"reason": item["summary"], "chapterid": chapter_id}
    return "chapter_segment", fact, evidence


def _atomic_annotation_fact(
    *,
    chapter_id: int,
    field_name: str,
    item: dict[str, Any],
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """2026-08-05 用于把各类章节原子事实规范化为统一图事实结构"""
    subject: dict[str, Any]
    object_value: dict[str, Any] | None = None
    value: Any | None = None
    predicate: str
    participants = list(item.get("participants") or [])
    fact_type = field_name.removesuffix("s")

    if field_name == "characters":
        subject = dict(item["entity"])
        predicate = str(item["action_type"])
        value = {
            "action": item["action"],
            "role_function": item["role_function"],
            "emotion": item["emotion"],
        }
    elif field_name == "locations":
        subject = dict(item["entity"])
        predicate = str(item["relation_type"])
        object_value = dict(item["location"])
    elif field_name == "dialogues":
        subject = dict(item["speaker"]) if item.get("speaker") else {
            "name": "未知说话人",
            "entity_type": "unknown",
        }
        predicate = "spoke"
        value = {
            "content": item["content"],
            "tone": item.get("tone"),
            "is_inner_monologue": item["is_inner_monologue"],
        }
    elif field_name == "events":
        subject = (
            dict(participants[0]["entity"])
            if participants
            else {"name": f"chapter:{chapter_id}:event", "entity_type": "event"}
        )
        predicate = str(item["event_type"])
        value = {"summary": item["summary"]}
    elif field_name == "relations":
        subject = dict(item["from_entity"])
        predicate = str(item["relation_type"])
        object_value = dict(item["to_entity"])
        participants = [
            {"role": "from", "entity": dict(item["from_entity"])},
            {"role": "to", "entity": dict(item["to_entity"])},
        ]
    elif field_name == "states":
        subject = dict(item["entity"])
        predicate = str(item["predicate"])
        object_value = dict(item["object"]) if item.get("object") is not None else None
        value = item.get("value")
    else:
        raise ValueError(f"不支持的章节事实字段: {field_name}")

    content = {"kind": field_name, **item}
    fact = {
        "fact_type": fact_type,
        "subject": subject,
        "predicate": predicate,
        "object": object_value,
        "value": value,
        "participants": participants,
        "scope": f"chapter:{chapter_id}",
        "story_time": item.get("story_time"),
        "assertion": "affirmed",
        "confidence": item["confidence"],
        "content": content,
    }
    return fact_type, fact, dict(item["evidence"])


def _iter_annotation_facts(
    row: ChapterAnnotationRecord,
) -> Iterator[tuple[str, str, dict[str, Any], dict[str, Any]]]:
    """2026-08-05 用于按稳定 payload 路径遍历章节正式标注的全部事实源"""
    payload = dict(row.payload)
    for index, item in enumerate(payload.get("segments", [])):
        path = f"segments/{index}"
        fact_type, fact, evidence = _segment_fact(chapter_id=row.chapter_id, item=dict(item))
        yield path, fact_type, fact, evidence
    for field_name in ("characters", "locations", "dialogues", "events", "relations", "states"):
        for index, item in enumerate(payload.get(field_name, [])):
            path = f"{field_name}/{index}"
            fact_type, fact, evidence = _atomic_annotation_fact(
                chapter_id=row.chapter_id,
                field_name=field_name,
                item=dict(item),
            )
            yield path, fact_type, fact, evidence


def _iter_entity_refs(fact: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """2026-08-05 用于从统一图事实中遍历真实业务实体并排除技术主体"""
    content = fact.get("content")
    content_payload = content if isinstance(content, dict) else {}
    content_kind = content_payload.get("kind")
    synthetic_subject = (
        content_kind == "segment"
        or (content_kind == "dialogues" and not content_payload.get("speaker"))
        or (content_kind == "events" and not content_payload.get("participants"))
    )
    subject = fact.get("subject")
    if isinstance(subject, dict) and not synthetic_subject:
        yield subject
    object_value = fact.get("object")
    if isinstance(object_value, dict) and "name" in object_value:
        yield object_value
    for participant in fact.get("participants") or []:
        entity = participant.get("entity") if isinstance(participant, dict) else None
        if isinstance(entity, dict):
            yield entity


def _upsert_graph_entity(
    session: Session,
    *,
    run_id: str,
    entity_ref: dict[str, Any],
    chunk_id: int | None,
    confidence: str,
    evidence: dict[str, Any],
) -> GraphEntity:
    """2026-08-05 用于从事实实体引用维护规范实体与主别名"""
    canonical_name = str(entity_ref["name"]).strip()
    entity_type = str(entity_ref["entity_type"]).strip()
    stmt = select(GraphEntity).where(
        GraphEntity.run_id == run_id,
        GraphEntity.canonical_name == canonical_name,
    )
    entity = session.execute(stmt).scalar_one_or_none()
    if entity is None:
        entity = GraphEntity(
            run_id=run_id,
            canonical_name=canonical_name,
            entity_type=entity_type,
            first_seen_chunk=chunk_id,
            last_seen_chunk=chunk_id,
            status="active",
            source_confidence=_CONFIDENCE_SCORE.get(confidence, 0.5),
        )
        session.add(entity)
        session.flush()
    else:
        if chunk_id is not None:
            if entity.first_seen_chunk is None or chunk_id < entity.first_seen_chunk:
                entity.first_seen_chunk = chunk_id
            if entity.last_seen_chunk is None or chunk_id > entity.last_seen_chunk:
                entity.last_seen_chunk = chunk_id
        entity.entity_type = entity_type
        entity.status = "active"
        entity.source_confidence = max(
            entity.source_confidence or 0.0,
            _CONFIDENCE_SCORE.get(confidence, 0.5),
        )

    alias_stmt = select(GraphEntityAlias).where(
        GraphEntityAlias.run_id == run_id,
        GraphEntityAlias.entity_id == entity.entity_id,
        GraphEntityAlias.alias == canonical_name,
    )
    if session.execute(alias_stmt).scalar_one_or_none() is None:
        session.add(
            GraphEntityAlias(
                run_id=run_id,
                entity_id=entity.entity_id,
                alias=canonical_name,
                source_chunk_id=chunk_id,
                evidence=json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                confidence=_CONFIDENCE_SCORE.get(confidence, 0.5),
                source_type="graph_fact",
                is_primary=True,
            )
        )
    return entity


def _upsert_graph_fact(
    session: Session,
    *,
    run_id: str,
    stable_fact_id: str,
    source_kind: str,
    fact: dict[str, Any],
    evidence: dict[str, Any],
    annotation_id: str | None = None,
    continuity_fact_id: str | None = None,
    payload_path: str | None = None,
) -> GraphFact:
    """2026-08-05 用于按稳定来源事实 ID 幂等写入图事实与来源关系"""
    source_stmt = select(GraphFactSource).where(
        GraphFactSource.run_id == run_id,
        GraphFactSource.stable_fact_id == stable_fact_id,
    )
    source = session.execute(source_stmt).scalar_one_or_none()
    if source is not None:
        graph_fact = session.get(GraphFact, source.graph_fact_id)
        if graph_fact is None:
            raise ValueError(f"graph_fact_source 指向不存在的图事实: {stable_fact_id}")
        return graph_fact

    graph_fact = GraphFact(
        run_id=run_id,
        stable_fact_id=stable_fact_id,
        fact_type=str(fact["fact_type"]),
        subject_name=str(fact["subject"]["name"]),
        subject_type=str(fact["subject"]["entity_type"]),
        predicate=str(fact["predicate"]),
        object=fact.get("object"),
        value=fact.get("value"),
        participants=list(fact.get("participants") or []),
        scope=str(fact["scope"]),
        story_time=fact.get("story_time"),
        assertion=str(fact["assertion"]),
        confidence=str(fact["confidence"]),
        content=dict(fact["content"]),
        active=True,
    )
    session.add(graph_fact)
    session.flush()
    session.add(
        GraphFactSource(
            run_id=run_id,
            graph_fact_id=graph_fact.graph_fact_id,
            stable_fact_id=stable_fact_id,
            source_kind=source_kind,
            annotation_id=annotation_id,
            continuity_fact_id=continuity_fact_id,
            payload_path=payload_path,
            evidence=evidence,
        )
    )
    chunk_id = fact["content"].get("chunk_id") if isinstance(fact.get("content"), dict) else None
    for entity_ref in _iter_entity_refs(fact):
        entity = _upsert_graph_entity(
            session,
            run_id=run_id,
            entity_ref=entity_ref,
            chunk_id=int(chunk_id) if chunk_id is not None else None,
            confidence=str(fact["confidence"]),
            evidence=evidence,
        )
        content = fact.get("content")
        if (
            isinstance(content, dict)
            and content.get("kind") == "characters"
            and entity_ref == fact.get("subject")
        ):
            entity.primary_role_function = str(content.get("role_function") or "") or None
            entity.last_action = str(content.get("action") or "") or None
            entity.last_emotion_score = str(content.get("emotion") or "") or None
    session.flush()
    return graph_fact


def _continuity_fact_payload(row: ContinuityFact) -> dict[str, Any]:
    """2026-08-05 用于把 continuity_facts 行转换为统一图事实语义"""
    content = {
        "kind": "continuity_fact",
        "fact_id": row.fact_id,
        "fact_type": row.fact_type,
        "subject": row.subject,
        "predicate": row.predicate,
        "object": row.object,
        "value": row.value,
        "participants": row.participants,
        "scope": row.scope,
        "story_time": row.story_time,
        "assertion": row.assertion,
        "change_kind": row.change_kind,
        "linked_fact_id": row.linked_fact_id,
        "confidence": row.confidence,
    }
    return {
        "fact_type": row.fact_type,
        "subject": dict(row.subject),
        "predicate": row.predicate,
        "object": row.object,
        "value": row.value,
        "participants": list(row.participants),
        "scope": row.scope,
        "story_time": row.story_time,
        "assertion": row.assertion,
        "confidence": row.confidence,
        "content": content,
    }


def _project_version_relation(session: Session, *, run_id: str, row: ContinuityFact) -> None:
    """2026-08-05 用于建立来源事实 refine supersede 与 retract 版本边"""
    if row.change_kind == "assert" or row.linked_fact_id is None:
        return
    previous_source_stmt = select(GraphFactSource).where(
        GraphFactSource.run_id == run_id,
        GraphFactSource.stable_fact_id == row.linked_fact_id,
    )
    previous_source = session.execute(previous_source_stmt).scalar_one_or_none()
    if previous_source is None:
        raise ValueError(f"linked_fact_id 尚未投影或不存在: {row.linked_fact_id}")
    existing_stmt = select(GraphFactVersion).where(
        GraphFactVersion.run_id == run_id,
        GraphFactVersion.previous_stable_fact_id == row.linked_fact_id,
        GraphFactVersion.current_stable_fact_id == row.fact_id,
    )
    if session.execute(existing_stmt).scalar_one_or_none() is None:
        session.add(
            GraphFactVersion(
                run_id=run_id,
                previous_stable_fact_id=row.linked_fact_id,
                current_stable_fact_id=row.fact_id,
                change_kind=row.change_kind,
            )
        )
    previous_fact = session.get(GraphFact, previous_source.graph_fact_id)
    if previous_fact is not None:
        previous_fact.active = False


def _chapter_anchor_chunks(session: Session, run_id: str) -> dict[int, int]:
    """2026-08-05 用于把章节 Evidence 转换为现有关系事件表需要的 chunk 锚点"""
    from sqlalchemy import func

    from src.storage.models import Chunk

    rows = session.execute(
        select(Chunk.chapter_id, func.min(Chunk.chunk_id).label("chunk_id"))
        .where(Chunk.run_id == run_id)
        .group_by(Chunk.chapter_id)
    ).all()
    return {int(row.chapter_id): int(row.chunk_id) for row in rows}


def _relation_projection_values(
    *,
    fact: GraphFact,
    source: GraphFactSource,
    chapter_anchor_chunks: dict[int, int],
) -> tuple[str, str, str, str, int, str] | None:
    """2026-08-05 用于从通用图事实提取关系事件投影所需的稳定语义"""
    content = fact.content if isinstance(fact.content, dict) else {}
    kind = content.get("kind")
    if kind == "relations":
        from_entity = content.get("from_entity")
        to_entity = content.get("to_entity")
        chunk_id = content.get("chunk_id")
        if not isinstance(from_entity, dict) or not isinstance(to_entity, dict) or not isinstance(chunk_id, int):
            return None
        return (
            str(from_entity.get("name") or "").strip(),
            str(to_entity.get("name") or "").strip(),
            fact.predicate,
            _CHANGE_LABEL.get(str(content.get("change_kind") or "assert"), "新建"),
            chunk_id,
            str(content.get("directionality") or "directed"),
        )
    if kind != "continuity_fact" or fact.fact_type != "relation" or not isinstance(fact.object, dict):
        return None
    evidence_chapter = source.evidence.get("chapterid") if isinstance(source.evidence, dict) else None
    if not isinstance(evidence_chapter, int) or evidence_chapter not in chapter_anchor_chunks:
        return None
    return (
        fact.subject_name.strip(),
        str(fact.object.get("name") or "").strip(),
        fact.predicate,
        _CHANGE_LABEL.get(str(content.get("change_kind") or "assert"), "新建"),
        chapter_anchor_chunks[evidence_chapter],
        "directed",
    )


def _project_relation_events(session: Session, *, run_id: str) -> None:
    """2026-08-05 用于从 graph_facts 幂等重建现有关系事件投影"""
    chapter_anchor_chunks = _chapter_anchor_chunks(session, run_id)
    entity_rows = list(
        session.execute(select(GraphEntity).where(GraphEntity.run_id == run_id)).scalars().all()
    )
    entities_by_name = {row.canonical_name: row for row in entity_rows}
    fact_stmt = (
        select(GraphFact, GraphFactSource)
        .join(GraphFactSource, GraphFactSource.graph_fact_id == GraphFact.graph_fact_id)
        .where(GraphFact.run_id == run_id, GraphFactSource.run_id == run_id)
        .order_by(GraphFact.graph_fact_id)
    )
    existing_events = {
        row.source_relation_row_id: row
        for row in session.execute(
            select(GraphRelationEvent).where(GraphRelationEvent.run_id == run_id)
        )
        .scalars()
        .all()
        if row.source_relation_row_id is not None
    }
    expected_source_ids: set[int] = set()
    for fact, source in session.execute(fact_stmt).all():
        values = _relation_projection_values(
            fact=fact,
            source=source,
            chapter_anchor_chunks=chapter_anchor_chunks,
        )
        if values is None:
            continue
        from_name, to_name, relation_type, change_type, chunk_id, directionality = values
        from_entity = entities_by_name.get(from_name)
        to_entity = entities_by_name.get(to_name)
        if from_entity is None or to_entity is None:
            raise ValueError(f"关系事实端点未投影为规范实体: {from_name} -> {to_name}")
        expected_source_ids.add(fact.graph_fact_id)
        reason = source.evidence.get("reason") if isinstance(source.evidence, dict) else None
        event = existing_events.get(fact.graph_fact_id)
        if event is None:
            event = GraphRelationEvent(
                run_id=run_id,
                from_entity_id=from_entity.entity_id,
                to_entity_id=to_entity.entity_id,
                relation_type=relation_type,
                change_type=change_type,
                chunk_id=chunk_id,
                evidence=str(reason) if reason else None,
                confidence=_CONFIDENCE_SCORE.get(fact.confidence),
                source_relation_row_id=fact.graph_fact_id,
                directionality=directionality,
            )
            session.add(event)
        else:
            event.from_entity_id = from_entity.entity_id
            event.to_entity_id = to_entity.entity_id
            event.relation_type = relation_type
            event.change_type = change_type
            event.chunk_id = chunk_id
            event.evidence = str(reason) if reason else None
            event.confidence = _CONFIDENCE_SCORE.get(fact.confidence)
            event.directionality = directionality
    stale_event_ids = [
        row.relation_event_id
        for source_id, row in existing_events.items()
        if source_id not in expected_source_ids
    ]
    if stale_event_ids:
        session.execute(
            delete(GraphRelationEvent).where(
                GraphRelationEvent.run_id == run_id,
                GraphRelationEvent.relation_event_id.in_(stale_event_ids),
            )
        )
    session.flush()


def _relation_pair(event: GraphRelationEvent) -> tuple[int, int]:
    """2026-08-05 用于按关系方向生成当前关系快照的实体对键"""
    if event.directionality == "bidirectional":
        return min(event.from_entity_id, event.to_entity_id), max(event.from_entity_id, event.to_entity_id)
    return event.from_entity_id, event.to_entity_id


def _project_relation_current_and_participants(session: Session, *, run_id: str) -> None:
    """2026-08-05 用于从关系事件重建当前关系与参与者统计投影"""
    session.execute(delete(GraphEntityParticipant).where(GraphEntityParticipant.run_id == run_id))
    session.execute(delete(GraphRelationCurrent).where(GraphRelationCurrent.run_id == run_id))
    events = list(
        session.execute(
            select(GraphRelationEvent)
            .where(GraphRelationEvent.run_id == run_id)
            .order_by(GraphRelationEvent.chunk_id, GraphRelationEvent.relation_event_id)
        )
        .scalars()
        .all()
    )
    grouped: dict[tuple[int, int], list[GraphRelationEvent]] = {}
    for event in events:
        grouped.setdefault(_relation_pair(event), []).append(event)

    active_counterparts: dict[int, set[int]] = {}
    for relation_events in grouped.values():
        first = relation_events[0]
        latest = relation_events[-1]
        is_active = latest.change_type != "断裂"
        tension = 0.0
        for event in relation_events:
            confidence = event.confidence or 0.5
            if event.relation_type == "敌对":
                tension += confidence
            elif event.relation_type in {"盟友", "友情"}:
                tension -= confidence * 0.5
        session.add(
            GraphRelationCurrent(
                run_id=run_id,
                from_entity_id=latest.from_entity_id,
                to_entity_id=latest.to_entity_id,
                current_type=latest.relation_type,
                first_seen_chunk=first.chunk_id,
                last_seen_chunk=latest.chunk_id,
                change_count=sum(1 for event in relation_events if event.change_type != "新建"),
                support_count=len(relation_events),
                latest_event_id=latest.relation_event_id,
                tension_index=tension,
                is_active=is_active,
            )
        )
        if is_active:
            active_counterparts.setdefault(latest.from_entity_id, set()).add(latest.to_entity_id)
            active_counterparts.setdefault(latest.to_entity_id, set()).add(latest.from_entity_id)

    events_by_entity: dict[int, list[GraphRelationEvent]] = {}
    historical_counterparts: dict[int, set[int]] = {}
    for event in events:
        events_by_entity.setdefault(event.from_entity_id, []).append(event)
        events_by_entity.setdefault(event.to_entity_id, []).append(event)
        historical_counterparts.setdefault(event.from_entity_id, set()).add(event.to_entity_id)
        historical_counterparts.setdefault(event.to_entity_id, set()).add(event.from_entity_id)
    for entity_id, entity_events in events_by_entity.items():
        latest = max(entity_events, key=lambda row: (row.chunk_id, row.relation_event_id))
        session.add(
            GraphEntityParticipant(
                run_id=run_id,
                entity_id=entity_id,
                relation_event_count=len(entity_events),
                current_degree=len(active_counterparts.get(entity_id, set())),
                historical_degree=len(historical_counterparts.get(entity_id, set())),
                first_relation_chunk=min(event.chunk_id for event in entity_events),
                last_relation_chunk=max(event.chunk_id for event in entity_events),
                latest_relation_event_id=latest.relation_event_id,
            )
        )
    session.flush()


def _project_relation_views(session: Session, *, run_id: str) -> None:
    """2026-08-05 用于从通用事实重建实体关系与参与者查询投影"""
    _project_relation_events(session, run_id=run_id)
    _project_relation_current_and_participants(session, run_id=run_id)


def _clear_graph_projection(session: Session, run_id: str) -> None:
    """2026-08-05 用于按外键顺序清空可从两类事实源完整重建的数据库图"""
    for model in (
        GraphFactVersion,
        GraphFactSource,
        GraphFact,
        GraphRelationCurrent,
        GraphEntityParticipant,
        GraphRelationEvent,
        GraphEntityAlias,
        GraphEntity,
    ):
        session.execute(delete(model).where(model.run_id == run_id))
    session.flush()


def project_graph_tables(
    run_id: str,
    *,
    session: Session,
    annotation_id: str | None = None,
    rebuild: bool = False,
) -> None:
    """2026-08-05 用于只从最终 chapter_annotations 与 continuity_facts 投影并 flush 数据库图"""
    if rebuild:
        _clear_graph_projection(session, run_id)

    annotation_stmt = select(ChapterAnnotationRecord).where(ChapterAnnotationRecord.run_id == run_id)
    if annotation_id is not None:
        annotation_stmt = annotation_stmt.where(ChapterAnnotationRecord.annotation_id == annotation_id)
    annotation_stmt = annotation_stmt.order_by(ChapterAnnotationRecord.chapter_id)
    annotations = list(session.execute(annotation_stmt).scalars().all())
    for annotation in annotations:
        for path, _fact_type, fact, evidence in _iter_annotation_facts(annotation):
            _upsert_graph_fact(
                session,
                run_id=run_id,
                stable_fact_id=stable_annotation_fact_id(annotation.annotation_id, path),
                source_kind="chapter_annotation",
                fact=fact,
                evidence=evidence,
                annotation_id=annotation.annotation_id,
                payload_path=path,
            )

    fact_stmt = select(ContinuityFact).where(ContinuityFact.run_id == run_id)
    if annotation_id is not None:
        fact_stmt = fact_stmt.where(ContinuityFact.created_by_annotation_id == annotation_id)
    fact_stmt = fact_stmt.order_by(ContinuityFact.created_at, ContinuityFact.fact_id)
    facts = list(session.execute(fact_stmt).scalars().all())
    for row in facts:
        _upsert_graph_fact(
            session,
            run_id=run_id,
            stable_fact_id=row.fact_id,
            source_kind="continuity_fact",
            fact=_continuity_fact_payload(row),
            evidence=dict(row.evidence),
            continuity_fact_id=row.fact_id,
        )
        _project_version_relation(session, run_id=run_id, row=row)
    _project_relation_views(session, run_id=run_id)
    session.flush()
