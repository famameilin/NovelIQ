"""
Agent 完成结果的持久化数据库图写入
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.agents.annotation.schema import CompletionFact, FactPushOutput
from src.storage.models import (
    ChapterAnnotationRecord,
    GraphEntity,
    GraphEntityParticipant,
    GraphFact,
    GraphFactSource,
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


@dataclass(frozen=True, slots=True)
class _RelationEdgeValues:
    """2026-08-06 用于承载图关系边及同一人物代表节点选择"""

    from_name: str
    to_name: str
    relation_type: str
    change_type: str
    chunk_id: int
    directionality: str
    relation_semantics: str
    representative_selector: dict[str, Any] | None


def _parse_entity_node_id(node_id: str) -> int:
    """2026-08-06 用于把图查询实体节点 ID 严格解析为数据库主键"""
    prefix, separator, raw_entity_id = node_id.partition(":")
    if (
        prefix != "entity"
        or separator != ":"
        or not raw_entity_id.isdigit()
        or raw_entity_id.startswith("0")
    ):
        raise ValueError(f"无效的图实体节点 ID: {node_id}")
    return int(raw_entity_id)


def stable_annotation_fact_id(annotation_id: str, payload_path: str) -> str:
    """2026-08-05 用于按 annotation_id 与 payload 路径生成可重建的稳定来源事实 ID"""
    digest = hashlib.sha256(f"{annotation_id}:{payload_path}".encode()).hexdigest()
    return f"ann_{digest}"


def stable_agent_resolution_fact_id(annotation_id: str, output_index: int) -> str:
    """2026-08-06 用于按完成事务与 fact 输出顺序生成稳定图节点键"""
    digest = hashlib.sha256(f"{annotation_id}:agent_resolution:{output_index}".encode()).hexdigest()
    return f"res_{digest}"


def graph_fact_node_id(stable_fact_id: str) -> str:
    """2026-08-06 用于把数据库图事实键转换为图查询统一节点 ID"""
    return f"fact:{stable_fact_id}"


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
    """2026-08-06 用于从图事实实体引用维护规范实体节点"""
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
            is_representative=True,
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
    payload_path: str | None = None,
    source_chunk_id: int | None = None,
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
            payload_path=payload_path,
            evidence=evidence,
        )
    )
    content_chunk_id = fact["content"].get("chunk_id") if isinstance(fact.get("content"), dict) else None
    chunk_id = content_chunk_id if isinstance(content_chunk_id, int) else source_chunk_id
    for entity_ref in _iter_entity_refs(fact):
        entity = _upsert_graph_entity(
            session,
            run_id=run_id,
            entity_ref=entity_ref,
            chunk_id=chunk_id,
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


def _agent_resolution_payload(output: FactPushOutput) -> dict[str, Any]:
    """2026-08-06 用于把 Agent fact 输出转换为数据库图节点关系与属性"""
    payload = output.payload.model_dump(mode="json")
    content = {
        "kind": "agent_resolution",
        "fact_type": payload["fact_type"],
        "subject": payload["subject"],
        "predicate": payload["predicate"],
        "object": payload["object"],
        "value": payload["value"],
        "participants": payload["participants"],
        "scope": payload["scope"],
        "story_time": payload["story_time"],
        "assertion": payload["assertion"],
        "confidence": payload["confidence"],
        "directionality": payload["directionality"],
        "relation_semantics": payload["relation_semantics"],
        "representative_node": payload["representative_node"],
    }
    return {
        "fact_type": payload["fact_type"],
        "subject": dict(payload["subject"]),
        "predicate": payload["predicate"],
        "object": payload["object"],
        "value": payload["value"],
        "participants": list(payload["participants"]),
        "scope": payload["scope"],
        "story_time": payload["story_time"],
        "assertion": payload["assertion"],
        "confidence": payload["confidence"],
        "content": content,
    }


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


def _relation_edge_values(
    *,
    fact: GraphFact,
    source: GraphFactSource,
    chapter_anchor_chunks: dict[int, int],
) -> _RelationEdgeValues | None:
    """2026-08-06 用于从通用图事实提取关系事件边所需的稳定语义"""
    content = fact.content if isinstance(fact.content, dict) else {}
    kind = content.get("kind")
    if kind == "relations":
        from_entity = content.get("from_entity")
        to_entity = content.get("to_entity")
        chunk_id = content.get("chunk_id")
        if not isinstance(from_entity, dict) or not isinstance(to_entity, dict) or not isinstance(chunk_id, int):
            return None
        representative = content.get("representative_node")
        return _RelationEdgeValues(
            from_name=str(from_entity.get("name") or "").strip(),
            to_name=str(to_entity.get("name") or "").strip(),
            relation_type=fact.predicate,
            change_type=_CHANGE_LABEL.get(str(content.get("change_kind") or "assert"), "新建"),
            chunk_id=chunk_id,
            directionality=str(content.get("directionality") or "directed"),
            relation_semantics=str(content.get("relation_semantics") or "ordinary"),
            representative_selector=dict(representative) if isinstance(representative, dict) else None,
        )
    if kind != "agent_resolution" or fact.fact_type != "relation" or not isinstance(fact.object, dict):
        return None
    evidence_chapter = source.evidence.get("chapterid") if isinstance(source.evidence, dict) else None
    if not isinstance(evidence_chapter, int) or evidence_chapter not in chapter_anchor_chunks:
        return None
    representative = content.get("representative_node")
    return _RelationEdgeValues(
        from_name=fact.subject_name.strip(),
        to_name=str(fact.object.get("name") or "").strip(),
        relation_type=fact.predicate,
        change_type="断裂" if fact.assertion == "negated" else "新建",
        chunk_id=chapter_anchor_chunks[evidence_chapter],
        directionality=str(content.get("directionality") or "directed"),
        relation_semantics=str(content.get("relation_semantics") or "ordinary"),
        representative_selector=dict(representative) if isinstance(representative, dict) else None,
    )


def _resolve_representative_entity_id(
    *,
    run_id: str,
    values: _RelationEdgeValues,
    from_entity: GraphEntity,
    to_entity: GraphEntity,
    entities_by_id: dict[int, GraphEntity],
) -> int:
    """2026-08-06 用于把端点或图搜索节点选择器解析为当前运行的真实人物节点 ID"""
    selector = values.representative_selector
    if selector is None:
        raise ValueError(
            f"同一人物关系缺少常用节点选择器: {values.from_name} -> {values.to_name}"
        )
    endpoint = selector.get("endpoint")
    node_id = selector.get("node_id")
    if (endpoint is None) == (node_id is None):
        raise ValueError("同一人物常用节点选择器必须恰好包含 endpoint 或 node_id")
    if endpoint == "subject":
        return from_entity.entity_id
    if endpoint == "object":
        return to_entity.entity_id
    if endpoint is not None:
        raise ValueError(f"无效的同一人物关系端点选择器: {endpoint}")
    if not isinstance(node_id, str):
        raise ValueError("同一人物常用节点 node_id 必须是字符串")
    entity_id = _parse_entity_node_id(node_id)
    selected = entities_by_id.get(entity_id)
    if selected is None or selected.run_id != run_id:
        raise ValueError(f"常用节点不属于当前 run_id: {node_id}")
    if selected.entity_type != "character":
        raise ValueError(f"常用节点必须是 character 节点: {node_id}")
    return selected.entity_id


def _sync_relation_events(session: Session, *, run_id: str) -> None:
    """2026-08-06 用于从数据库图事实同步关系事件边"""
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
        values = _relation_edge_values(
            fact=fact,
            source=source,
            chapter_anchor_chunks=chapter_anchor_chunks,
        )
        if values is None:
            continue
        from_entity = entities_by_name.get(values.from_name)
        to_entity = entities_by_name.get(values.to_name)
        if from_entity is None or to_entity is None:
            raise ValueError(f"关系事实端点缺少实体节点: {values.from_name} -> {values.to_name}")
        expected_source_ids.add(fact.graph_fact_id)
        reason = source.evidence.get("reason") if isinstance(source.evidence, dict) else None
        event = existing_events.get(fact.graph_fact_id)
        if event is None:
            event = GraphRelationEvent(
                run_id=run_id,
                from_entity_id=from_entity.entity_id,
                to_entity_id=to_entity.entity_id,
                relation_type=values.relation_type,
                change_type=values.change_type,
                chunk_id=values.chunk_id,
                evidence=str(reason) if reason else None,
                confidence=_CONFIDENCE_SCORE.get(fact.confidence),
                source_relation_row_id=fact.graph_fact_id,
                directionality=values.directionality,
            )
            session.add(event)
        else:
            event.from_entity_id = from_entity.entity_id
            event.to_entity_id = to_entity.entity_id
            event.relation_type = values.relation_type
            event.change_type = values.change_type
            event.chunk_id = values.chunk_id
            event.evidence = str(reason) if reason else None
            event.confidence = _CONFIDENCE_SCORE.get(fact.confidence)
            event.directionality = values.directionality
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


def _sync_relation_current_and_participants(session: Session, *, run_id: str) -> None:
    """2026-08-06 用于从关系事件同步当前关系边与参与者属性"""
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


def _active_identity_edges(
    session: Session,
    *,
    run_id: str,
    entities_by_name: dict[str, GraphEntity],
    entities_by_id: dict[int, GraphEntity],
) -> list[tuple[int, int, int, int]]:
    """2026-08-06 用于读取当前有效同一人物边及其代表节点选择"""
    chapter_anchor_chunks = _chapter_anchor_chunks(session, run_id)
    fact_stmt = (
        select(GraphFact, GraphFactSource)
        .join(GraphFactSource, GraphFactSource.graph_fact_id == GraphFact.graph_fact_id)
        .where(GraphFact.run_id == run_id, GraphFactSource.run_id == run_id)
        .order_by(GraphFact.graph_fact_id)
    )
    latest_by_pair: dict[tuple[int, int], tuple[int, _RelationEdgeValues]] = {}
    for fact, source in session.execute(fact_stmt).all():
        values = _relation_edge_values(
            fact=fact,
            source=source,
            chapter_anchor_chunks=chapter_anchor_chunks,
        )
        if values is None or values.relation_semantics != "same_character":
            continue
        from_entity = entities_by_name.get(values.from_name)
        to_entity = entities_by_name.get(values.to_name)
        if from_entity is None or to_entity is None:
            raise ValueError(f"同一人物关系端点缺少实体节点: {values.from_name} -> {values.to_name}")
        if from_entity.entity_type != "character" or to_entity.entity_type != "character":
            raise ValueError("同一人物关系的两端必须都是 character 节点")
        if from_entity.entity_id == to_entity.entity_id:
            raise ValueError("同一人物关系必须连接两个独立 character 节点")
        if values.directionality != "bidirectional":
            raise ValueError("同一人物关系必须使用 bidirectional")
        left_entity_id, right_entity_id = sorted((from_entity.entity_id, to_entity.entity_id))
        pair = (left_entity_id, right_entity_id)
        latest_by_pair[pair] = (fact.graph_fact_id, values)

    active_edges: list[tuple[int, int, int, int]] = []
    for (from_entity_id, to_entity_id), (graph_fact_id, values) in latest_by_pair.items():
        if values.change_type == "断裂":
            continue
        original_from_entity = entities_by_name[values.from_name]
        original_to_entity = entities_by_name[values.to_name]
        representative_entity_id = _resolve_representative_entity_id(
            run_id=run_id,
            values=values,
            from_entity=original_from_entity,
            to_entity=original_to_entity,
            entities_by_id=entities_by_id,
        )
        active_edges.append(
            (
                graph_fact_id,
                from_entity_id,
                to_entity_id,
                representative_entity_id,
            )
        )
    return active_edges


def _identity_components(active_edges: list[tuple[int, int, int, int]]) -> list[set[int]]:
    """2026-08-06 用于从有效同一人物边构建人物节点连通分量"""
    adjacency: dict[int, set[int]] = {}
    for _graph_fact_id, from_entity_id, to_entity_id, _representative_entity_id in active_edges:
        adjacency.setdefault(from_entity_id, set()).add(to_entity_id)
        adjacency.setdefault(to_entity_id, set()).add(from_entity_id)

    components: list[set[int]] = []
    visited: set[int] = set()
    for root in sorted(adjacency):
        if root in visited:
            continue
        component: set[int] = set()
        pending = [root]
        while pending:
            entity_id = pending.pop()
            if entity_id in visited:
                continue
            visited.add(entity_id)
            component.add(entity_id)
            pending.extend(sorted(adjacency.get(entity_id, set()) - visited, reverse=True))
        components.append(component)
    return components


def _sync_character_representatives(session: Session, *, run_id: str) -> None:
    """2026-08-06 用于按同一人物连通分量选举并标记唯一常用人物节点"""
    entities = list(
        session.execute(
            select(GraphEntity)
            .where(GraphEntity.run_id == run_id)
            .order_by(GraphEntity.entity_id)
        )
        .scalars()
        .all()
    )
    entities_by_name = {entity.canonical_name: entity for entity in entities}
    entities_by_id = {entity.entity_id: entity for entity in entities}
    character_entities = [entity for entity in entities if entity.entity_type == "character"]
    for entity in character_entities:
        entity.is_representative = True

    active_edges = _active_identity_edges(
        session,
        run_id=run_id,
        entities_by_name=entities_by_name,
        entities_by_id=entities_by_id,
    )
    for component in _identity_components(active_edges):
        component_edges = [
            edge
            for edge in active_edges
            if edge[1] in component and edge[2] in component
        ]
        latest_edge = max(component_edges, key=lambda edge: edge[0])
        representative_entity_id = latest_edge[3]
        if representative_entity_id not in component:
            selected = entities_by_id.get(representative_entity_id)
            selected_name = selected.canonical_name if selected is not None else representative_entity_id
            raise ValueError(f"代表节点不属于同一人物连通分量: {selected_name}")
        for entity_id in component:
            entity = entities_by_id[entity_id]
            entity.is_representative = entity_id == representative_entity_id
    session.flush()


def _sync_relation_graph(session: Session, *, run_id: str) -> None:
    """2026-08-06 用于同步数据库图中的关系边参与者与常用人物节点"""
    _sync_relation_events(session, run_id=run_id)
    _sync_relation_current_and_participants(session, run_id=run_id)
    _sync_character_representatives(session, run_id=run_id)


def persist_completion_graph(
    session: Session,
    *,
    annotation: ChapterAnnotationRecord,
    fact_outputs: list[FactPushOutput],
) -> list[CompletionFact]:
    """2026-08-06 用于在 Agent END 后直接持久化正式标注与已解决案例图结果"""
    run_id = annotation.run_id
    chapter_anchor_chunks = _chapter_anchor_chunks(session, run_id)

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

    completions: list[CompletionFact] = []
    for output_index, output in enumerate(fact_outputs):
        stable_fact_id = stable_agent_resolution_fact_id(annotation.annotation_id, output_index)
        evidence = output.evidence.model_dump(mode="json")
        _upsert_graph_fact(
            session,
            run_id=run_id,
            stable_fact_id=stable_fact_id,
            source_kind="agent_resolution",
            fact=_agent_resolution_payload(output),
            evidence=evidence,
            annotation_id=annotation.annotation_id,
            payload_path=f"agent_resolutions/{output_index}",
            source_chunk_id=chapter_anchor_chunks.get(output.evidence.chapterid),
        )
        completions.append(
            CompletionFact(
                graph_node_id=graph_fact_node_id(stable_fact_id),
                payload=output.payload,
                evidence=output.evidence,
            )
        )

    _sync_relation_graph(session, run_id=run_id)
    session.flush()
    return completions
