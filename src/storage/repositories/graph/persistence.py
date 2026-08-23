"""章节标注到图谱当前状态的原子写入"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents.annotation.schema import (
    RELATION_DEFINITIONS,
    BoundChapterAnnotation,
    BoundEntity,
    EntityType,
    ResolvedCase,
)
from src.storage.models import (
    Chapter,
    ChapterAnnotationRecord,
    DialogueRecord,
    EntityState,
    EventEdge,
    EventNode,
    ForeshadowingThread,
    GraphEntity,
    GraphFact,
    GraphRelation,
    Paragraph,
    RelationState,
)
from src.storage.models.graph import ChapterBoundary


@dataclass(slots=True)
class PersistedGraphResult:
    """2026-08-19 用于返回章节边界和案例解决目标"""

    chapter_boundary: ChapterBoundary
    resolved_targets_by_case_id: dict[str, Any]


@dataclass(slots=True)
class _RelationDraft:
    """2026-08-19 用于在当前章节汇总同一稳定关系的状态"""

    relation: GraphRelation
    relation_type: str
    attributes: dict[str, Any]
    is_active: bool
    changes: list[dict[str, Any]]


def _normalized_name(value: str) -> str:
    """2026-08-19 用于生成实体名称精确解析键"""
    return unicodedata.normalize("NFC", value).strip().casefold()


def stable_annotation_fact_id(annotation_id: str, chapter_id: int, domain: str, ordinal: int) -> str:
    """2026-08-19 用于按章节标注位置生成稳定事实 ID"""
    return str(uuid5(UUID(annotation_id), f"{chapter_id}:{domain}:{ordinal}"))


def _relation_id(
    run_id: str,
    from_entity_id: int,
    to_entity_id: int,
    relation_type: str,
    directionality: str,
) -> str:
    """2026-08-19 用于根据实体端点和关系语义生成稳定关系 ID"""
    left_id, right_id = from_entity_id, to_entity_id
    if directionality == "bidirectional" and left_id > right_id:
        left_id, right_id = right_id, left_id
    return str(uuid5(NAMESPACE_URL, f"noveliq:relation:{run_id}:{left_id}:{right_id}:{relation_type}:{directionality}"))


def _event_edge_id(run_id: str, source_event_id: str, target_event_id: str) -> str:
    """2026-08-19 用于按运行和事件端点生成稳定因果边 ID"""
    return str(uuid5(NAMESPACE_URL, f"noveliq:event-edge:{run_id}:causal:{source_event_id}:{target_event_id}"))


def _chapter_order_map(session: Session, run_id: str) -> dict[int, int]:
    """2026-08-19 用于把章节身份映射为历史排序"""
    chapters = session.execute(
        select(Chapter)
        .where(Chapter.run_id == run_id, Chapter.text.isnot(None))
        .order_by(Chapter.sequence, Chapter.chapter_id)
    ).scalars()
    return {int(chapter.chapter_id): index for index, chapter in enumerate(chapters, start=1)}


def _chapter_text_evidence(session: Session, *, run_id: str, chapter_id: int) -> list[dict[str, Any]]:
    """2026-08-19 用于为事实生成当前章节原文证据"""
    chapter = session.execute(
        select(Chapter).where(Chapter.run_id == run_id, Chapter.chapter_id == chapter_id)
    ).scalar_one_or_none()
    paragraphs = list(
        session.execute(
            select(Paragraph)
            .where(Paragraph.run_id == run_id, Paragraph.chapter_id == chapter_id)
            .order_by(Paragraph.paragraph_index)
        ).scalars()
    )
    if chapter is None or chapter.text is None or not paragraphs:
        raise ValueError(f"事实缺少可生成 Evidence 的章节段落: run_id={run_id} chapter_id={chapter_id}")
    start = min(int(row.local_start_char) for row in paragraphs)
    end = max(int(row.local_end_char) for row in paragraphs)
    return [
        {
            "paragraph_ids": [int(row.paragraph_id) for row in paragraphs],
            "char_start": start,
            "char_end": end,
            "text_hash": hashlib.sha256(chapter.text[start:end].encode("utf-8")).hexdigest(),
        }
    ]


def _entity_attributes(entity: BoundEntity, entity_type: EntityType) -> dict[str, Any]:
    """2026-08-19 用于提取实体本次提交的属性"""
    attributes: dict[str, Any] = {"entity_type": entity_type}
    if entity.description is not None:
        attributes["description"] = entity.description
    attributes.update(entity.attributes or {})
    return attributes


def _resolve_entities(
    session: Session,
    *,
    annotation: ChapterAnnotationRecord,
    payload: BoundChapterAnnotation,
) -> tuple[dict[str, GraphEntity], dict[int, list[dict[str, Any]]]]:
    """2026-08-19 用于按规范化名称匹配或创建实体并记录属性变化"""
    appearances: dict[str, list[tuple[int, EntityType, BoundEntity]]] = {}
    display_names: dict[str, str] = {}
    for chunk in payload.chunks:
        for item in chunk.entities.entities:
            key = _normalized_name(item.name)
            if key in display_names and display_names[key] != item.name:
                raise ValueError(f"实体名称规范化后冲突: {display_names[key]} / {item.name}")
            display_names[key] = item.name
            appearances.setdefault(key, []).append((chunk.chunk_id, item.entity_type, item))
    existing = {
        _normalized_name(entity.canonical_name): entity
        for entity in session.execute(select(GraphEntity).where(GraphEntity.run_id == annotation.run_id)).scalars()
    }
    resolved: dict[str, GraphEntity] = {}
    patches: dict[int, list[dict[str, Any]]] = {}
    for key, items in appearances.items():
        types = {item_type for _chapter, item_type, _item in items}
        if len(types) != 1:
            raise ValueError(f"同一实体名称被声明为多个大类: {display_names[key]}")
        entity_type = next(iter(types))
        chapter_ids = [chapter for chapter, _item_type, _item in items]
        attributes: dict[str, Any] = {}
        tags: list[str] = []
        for _chapter, _item_type, item in items:
            attributes.update(_entity_attributes(item, entity_type))
            tags.extend(tag for tag in item.tags if tag not in tags)
        entity = existing.get(key)
        if entity is not None and entity.entity_type != entity_type:
            raise ValueError(f"实体名称已属于其他大类: {display_names[key]}")
        if entity is None:
            entity = GraphEntity(
                run_id=annotation.run_id,
                canonical_name=display_names[key],
                entity_type=entity_type,
                tags=tags,
                attributes=attributes,
                first_seen_chapter=min(chapter_ids),
                last_seen_chapter=max(chapter_ids),
            )
            session.add(entity)
            session.flush()
            existing[key] = entity
        else:
            before = dict(entity.attributes or {})
            merged = dict(before)
            for field_name, value in attributes.items():
                if value is None:
                    merged.pop(field_name, None)
                else:
                    merged[field_name] = value
            entity.attributes = merged
            entity.tags = tags or list(entity.tags or [])
            entity.first_seen_chapter = min(int(entity.first_seen_chapter), min(chapter_ids))
            entity.last_seen_chapter = max(int(entity.last_seen_chapter), max(chapter_ids))
            for field_name in before.keys() | merged.keys():
                if before.get(field_name) != merged.get(field_name):
                    patches.setdefault(int(entity.entity_id), []).append(
                        {
                            "field": field_name,
                            "before": before.get(field_name),
                            "after": merged.get(field_name),
                            "chapter_id": min(chapter_ids),
                        }
                    )
        resolved[key] = entity
    for key, entity in existing.items():
        resolved.setdefault(key, entity)
    return resolved, patches


def _entity(entities: dict[str, GraphEntity], name: str | None) -> GraphEntity | None:
    """2026-08-19 用于按名称读取已解析实体"""
    if name is None:
        return None
    entity = entities.get(_normalized_name(name))
    if entity is None:
        raise ValueError(f"事实端点实体未被系统解析: {name}")
    return entity


def _entity_descriptor(entity: GraphEntity | None) -> dict[str, Any] | None:
    """2026-08-19 用于把实体转换为稳定事实描述"""
    if entity is None:
        return None
    return {
        "entity_id": int(entity.entity_id),
        "name": str(entity.canonical_name),
        "entity_type": str(entity.entity_type),
    }


def _new_fact(
    *,
    annotation: ChapterAnnotationRecord,
    chapter_id: int,
    domain: str,
    ordinal: int,
    subject: GraphEntity | None,
    predicate: str,
    object_value: dict[str, Any] | None,
    value: Any | None,
    participants: list[dict[str, Any]],
    content: dict[str, Any],
    evidence: list[dict[str, Any]],
    event_id: str | None = None,
    fact_id: str | None = None,
    payload_path: str | None = None,
) -> GraphFact:
    """2026-08-19 用于构造单个章节事实"""
    if not evidence:
        raise ValueError("事实必须携带非空 Evidence")
    resolved_fact_id = fact_id
    if resolved_fact_id is None:
        resolved_fact_id = stable_annotation_fact_id(annotation.annotation_id, chapter_id, domain, ordinal)
    resolved_payload_path = payload_path
    if resolved_payload_path is None:
        resolved_payload_path = f"chunks/{chapter_id}/{domain}/{ordinal}"
    return GraphFact(
        run_id=annotation.run_id,
        chapter_id=chapter_id,
        fact_id=resolved_fact_id,
        fact_type=domain,
        subject_entity_id=int(subject.entity_id) if subject is not None else None,
        predicate=predicate,
        object=object_value,
        value=value,
        participants=participants,
        scope=f"chapter:{annotation.chapter_id}:chunk:{chapter_id}",
        story_time=None,
        assertion="affirmed",
        confidence="medium",
        content=content,
        effective_chapter_id=chapter_id,
        source_kind="annotation",
        annotation_id=annotation.annotation_id,
        payload_path=resolved_payload_path,
        event_id=event_id,
        evidence=evidence,
    )


def _previous_state(session: Session, *, run_id: str, entity_id: int, chapter_order: int) -> dict[str, Any]:
    """2026-08-19 用于读取目标章节之前最近的实体状态"""
    order_map = _chapter_order_map(session, run_id)
    rows = session.execute(select(EntityState).where(EntityState.run_id == run_id)).scalars()
    candidates = [
        row for row in rows if order_map.get(int(row.chapter_id), 0) < chapter_order and row.entity_id == entity_id
    ]
    if not candidates:
        return {}
    latest = max(candidates, key=lambda row: order_map.get(int(row.chapter_id), 0))
    return dict(latest.state)


def _state_updates(fact: GraphFact) -> dict[str, Any]:
    """2026-08-19 用于把事实转换为实体状态字段更新"""
    if fact.content.get("kind") == "character_observation":
        return {
            "role_function": fact.content.get("role_function"),
            "action": fact.content.get("action"),
            "emotion": fact.content.get("emotion"),
        }
    return {}


def _persist_state_rows(
    session: Session,
    *,
    annotation: ChapterAnnotationRecord,
    boundary: ChapterBoundary,
    facts: list[GraphFact],
    entities: dict[str, GraphEntity],
    attribute_changes: dict[int, list[dict[str, Any]]],
) -> None:
    """2026-08-19 用于按章节写入实体状态行并继承前序状态"""
    entity_by_id = {int(entity.entity_id): entity for entity in entities.values()}
    updates_by_entity: dict[int, list[dict[str, Any]]] = {}
    for fact in facts:
        if fact.subject_entity_id is not None:
            updates = _state_updates(fact)
            if updates:
                updates_by_entity.setdefault(int(fact.subject_entity_id), []).append(
                    {"fact_id": fact.fact_id, "chapter_id": fact.chapter_id, **updates}
                )
    for entity_id, changes in attribute_changes.items():
        updates_by_entity.setdefault(entity_id, []).extend(
            {"fact_id": change.get("fact_id", ""), **change} for change in changes
        )
    # 实体属性发生变化时需要形成章节状态快照，供历史图查询继承
    for entity_id, entity in entity_by_id.items():
        dynamic_attributes = {
            key: value
            for key, value in dict(entity.attributes or {}).items()
            if key not in {"entity_type", "description"}
        }
        if dynamic_attributes and int(entity.first_seen_chapter) == annotation.chapter_id:
            updates_by_entity.setdefault(entity_id, []).extend(
                {
                    "field": key,
                    "before": None,
                    "after": value,
                    "fact_id": "",
                    "chapter_id": annotation.chapter_id,
                }
                for key, value in dynamic_attributes.items()
            )
    for entity_id, changes in updates_by_entity.items():
        state_entity = entity_by_id.get(entity_id)
        if state_entity is None:
            continue
        state = {
            **dict(state_entity.attributes or {}),
            **_previous_state(
                session, run_id=annotation.run_id, entity_id=entity_id, chapter_order=boundary.chapter_order
            ),
        }
        normalized_changes: list[dict[str, Any]] = []
        for change in changes:
            field_names = (
                ["field"]
                if "field" in change
                else [field_name for field_name in ("role_function", "action", "emotion") if field_name in change]
            )
            for field_name in field_names:
                actual_field = str(change.get("field", field_name))
                after = change.get("after", change.get(field_name))
                if "before" in change and state.get(actual_field) != change.get("before"):
                    expected_before = change.get("before")
                    if expected_before is None:
                        state.pop(actual_field, None)
                    else:
                        state[actual_field] = expected_before
                before = state.get(actual_field)
                if before == after:
                    continue
                if after is None:
                    state.pop(actual_field, None)
                else:
                    state[actual_field] = after
                normalized_changes.append(
                    {
                        "field": actual_field,
                        "before": before,
                        "after": after,
                        "fact_id": change.get("fact_id", ""),
                        "chapter_id": change.get("chapter_id", annotation.chapter_id),
                    }
                )
        if not normalized_changes:
            continue
        row = session.get(EntityState, (annotation.run_id, annotation.chapter_id, entity_id))
        if row is None:
            session.add(
                EntityState(
                    run_id=annotation.run_id,
                    chapter_id=annotation.chapter_id,
                    entity_id=entity_id,
                    state=state,
                    changes=normalized_changes,
                )
            )
        else:
            row.state = state
            row.changes = [*row.changes, *normalized_changes]


def _relation_key(from_id: int, to_id: int, relation_type: str, directionality: str) -> tuple[int, int, str, str]:
    """2026-08-19 用于生成关系状态查找键"""
    if directionality == "bidirectional" and from_id > to_id:
        from_id, to_id = to_id, from_id
    return from_id, to_id, relation_type, directionality


def _relation_draft(
    session: Session,
    *,
    run_id: str,
    relation: GraphRelation,
    chapter_order: int,
    relation_type: str,
    current_chapter_id: int | None = None,
) -> _RelationDraft:
    """2026-08-20 用于读取关系此前最近状态并纳入当前事务尚未 flush 的章节状态"""
    order_map = _chapter_order_map(session, run_id)
    rows: list[RelationState] = [
        row
        for row in session.execute(
            select(RelationState).where(
                RelationState.run_id == run_id, RelationState.relation_id == relation.relation_id
            )
        ).scalars()
        if order_map.get(int(row.chapter_id), 0) < chapter_order
    ]
    if current_chapter_id is not None:
        # 案例解决前已写入的同章状态必须参与合并；显式 flush 兼容生产 autoflush=False
        session.flush()
        current_rows = session.execute(
            select(RelationState).where(
                RelationState.run_id == run_id,
                RelationState.relation_id == relation.relation_id,
                RelationState.chapter_id == current_chapter_id,
            )
        ).scalars()
        rows.extend(row for row in current_rows if row not in rows)
    latest = max(rows, key=lambda row: order_map.get(int(row.chapter_id), 0)) if rows else None
    return _RelationDraft(
        relation=relation,
        relation_type=str(latest.relation_type) if latest is not None else relation_type,
        attributes=dict(latest.attributes) if latest is not None else {},
        is_active=bool(latest.is_active) if latest is not None else False,
        # changes 只保存本次调用新增的变化；已有状态仅用于初始化 before/当前属性
        changes=[],
    )


def _apply_relation_change(draft: _RelationDraft, *, fact: GraphFact, change_kind: str, relation_type: str) -> None:
    """2026-08-19 用于应用关系生命周期变化"""
    before = {"relation_type": draft.relation_type, "attributes": dict(draft.attributes), "is_active": draft.is_active}
    if change_kind in {"assert", "reinforce", "refine", "supersede", "noop"}:
        draft.relation_type = relation_type
        draft.is_active = True
        draft.attributes["support_count"] = int(draft.attributes.get("support_count", 0)) + (
            0 if change_kind == "noop" else 1
        )
    elif change_kind == "weaken":
        draft.attributes["strength"] = int(draft.attributes.get("strength", 0)) - 1
    elif change_kind in {"break", "retract"}:
        draft.is_active = False
    else:
        raise ValueError(f"不支持的关系变化类型: {change_kind}")
    draft.changes.append(
        {
            "change_kind": change_kind,
            "before": before,
            "after": {
                "relation_type": draft.relation_type,
                "attributes": dict(draft.attributes),
                "is_active": draft.is_active,
            },
            "fact_id": fact.fact_id,
            "chapter_id": fact.chapter_id,
        }
    )


def _persist_relation_state(session: Session, *, annotation: ChapterAnnotationRecord, draft: _RelationDraft) -> None:
    """2026-08-19 用于写入当前章节关系状态"""
    if not draft.changes:
        return
    row = session.get(RelationState, (annotation.run_id, annotation.chapter_id, draft.relation.relation_id))
    if row is None:
        session.add(
            RelationState(
                run_id=annotation.run_id,
                chapter_id=annotation.chapter_id,
                relation_id=draft.relation.relation_id,
                relation_type=draft.relation_type,
                attributes=draft.attributes,
                is_active=draft.is_active,
                changes=draft.changes,
            )
        )
    else:
        row.relation_type = draft.relation_type
        row.attributes = draft.attributes
        row.is_active = draft.is_active
        row.changes = [*row.changes, *draft.changes]


def _persist_event_nodes(
    session: Session,
    *,
    annotation: ChapterAnnotationRecord,
    boundary: ChapterBoundary,
    chunk: Any,
    entities: dict[str, GraphEntity],
) -> dict[int, str]:
    """2026-08-19 用于写入事件节点及当前章节因果边

    2026-08-22event_id 直接取服务端生成的 node_id；因果边只存在于
    跨章树根（cause_tree_id），由 create_event 结构性保证无环，DAG 校验删除。
    2026-08-22 重构：章级证据单份派生并盖章到每个节点（节点不再携带证据字段）。
    """
    chapter_evidence = _chapter_text_evidence(
        session, run_id=annotation.run_id, chapter_id=chunk.chunk_id
    )[0]
    event_ids: dict[int, str] = {}
    for index, event in enumerate(chunk.events, start=1):
        event_id = event.node_id
        event_ids[index] = event_id
        participants = [
            {"role": participant.role, "entity": _entity_descriptor(_entity(entities, participant.entity))}
            for participant in event.participants
        ]
        node = session.get(EventNode, event_id)
        if node is None:
            session.add(
                EventNode(
                    event_id=event_id,
                    run_id=annotation.run_id,
                    chapter_id=chunk.chunk_id,
                    chapter_order=boundary.chapter_order,
                    description=event.description,
                    participants=participants,
                    anchor_paragraph_ids=list(chapter_evidence["paragraph_ids"]),
                    char_start=int(chapter_evidence["char_start"]),
                    char_end=int(chapter_evidence["char_end"]),
                    text_hash=str(chapter_evidence["text_hash"]),
                    evidence=[dict(chapter_evidence)],
                    causal_event_refs=list(event.causal_event_refs),
                    tree_id=event.tree_id,
                    cause_role=event.cause_role,
                    annotation_id=annotation.annotation_id,
                    source_kind="annotation",
                    payload_path=f"chunks/{chunk.chunk_id}/events/{index}",
                )
            )
    session.flush()
    for index, event in enumerate(chunk.events, start=1):
        target_id = event_ids[index]
        for source_id in event.causal_event_refs:
            source = session.execute(
                select(EventNode).where(EventNode.run_id == annotation.run_id, EventNode.event_id == source_id)
            ).scalar_one_or_none()
            if source is None:
                raise ValueError(f"因果事件不存在或跨 run: {source_id}")
            edge_id = _event_edge_id(annotation.run_id, source_id, target_id)
            if session.get(EventEdge, edge_id) is None:
                session.add(
                    EventEdge(
                        edge_id=edge_id,
                        run_id=annotation.run_id,
                        edge_type="causal",
                        source_event_id=source_id,
                        target_event_id=target_id,
                        source_chapter_id=source.chapter_id,
                        target_chapter_id=chunk.chunk_id,
                        is_active=True,
                        evidence=[dict(chapter_evidence)],
                        annotation_id=annotation.annotation_id,
                        payload_path=f"chunks/{chunk.chunk_id}/events/{index}/causes/{source_id}",
                    )
                )
    return event_ids


def _persist_annotation_facts(
    session: Session,
    *,
    annotation: ChapterAnnotationRecord,
    boundary: ChapterBoundary,
    payload: BoundChapterAnnotation,
    entities: dict[str, GraphEntity],
    attribute_changes: dict[int, list[dict[str, Any]]],
) -> list[GraphFact]:
    """2026-08-19 用于写入当前章节事实、事件和关系状态"""
    facts: list[GraphFact] = []
    relation_drafts: dict[str, _RelationDraft] = {}
    for chunk in payload.chunks:
        evidence = _chapter_text_evidence(session, run_id=annotation.run_id, chapter_id=chunk.chunk_id)
        event_ids = _persist_event_nodes(
            session, annotation=annotation, boundary=boundary, chunk=chunk, entities=entities
        )
        for ordinal, observation in enumerate(chunk.character_observations, start=1):
            subject = _entity(entities, observation.character)
            facts.append(
                _new_fact(
                    annotation=annotation,
                    chapter_id=chunk.chunk_id,
                    domain="character_observation",
                    ordinal=ordinal,
                    subject=subject,
                    predicate="observation",
                    object_value=None,
                    value={
                        "role_function": observation.role_function,
                        "action": observation.action,
                        "emotion": observation.emotion,
                    },
                    participants=[],
                    content={
                        "kind": "character_observation",
                        "chapter_id": chunk.chunk_id,
                        "entity": _entity_descriptor(subject),
                        "role_function": observation.role_function,
                        "action": observation.action,
                        "emotion": observation.emotion,
                    },
                    evidence=evidence,
                )
            )
        for ordinal, event in enumerate(chunk.events, start=1):
            participants = [
                {"role": participant.role, "entity": _entity_descriptor(_entity(entities, participant.entity))}
                for participant in event.participants
            ]
            facts.append(
                _new_fact(
                    annotation=annotation,
                    chapter_id=chunk.chunk_id,
                    domain="event",
                    ordinal=ordinal,
                    subject=_entity(entities, event.participants[0].entity) if event.participants else None,
                    predicate="event",
                    object_value=None,
                    value={"description": event.description},
                    participants=participants,
                    content={
                        "kind": "event",
                        "chapter_id": chunk.chunk_id,
                        "description": event.description,
                        "anchor_paragraph_ids": list(evidence[0]["paragraph_ids"]),
                    },
                    evidence=evidence,
                    event_id=event_ids[ordinal],
                )
            )
        for ordinal, relation_item in enumerate(chunk.relations, start=1):
            from_entity = _entity(entities, relation_item.from_entity)
            to_entity = _entity(entities, relation_item.to_entity)
            if from_entity is None or to_entity is None:
                raise ValueError("relation 端点缺少实体")
            relation_id = _relation_id(
                annotation.run_id,
                int(from_entity.entity_id),
                int(to_entity.entity_id),
                str(relation_item.relation_type),
                str(relation_item.directionality),
            )
            relation = session.get(GraphRelation, relation_id)
            if relation is None:
                relation = GraphRelation(
                    relation_id=relation_id,
                    run_id=annotation.run_id,
                    from_entity_id=int(from_entity.entity_id),
                    to_entity_id=int(to_entity.entity_id),
                    directionality=str(relation_item.directionality),
                    relation_semantics=str(relation_item.relation_semantics),
                )
                session.add(relation)
                session.flush()
            draft = relation_drafts.setdefault(
                relation_id,
                _relation_draft(
                    session,
                    run_id=annotation.run_id,
                    relation=relation,
                    chapter_order=boundary.chapter_order,
                    relation_type=str(relation_item.relation_type),
                    current_chapter_id=annotation.chapter_id,
                ),
            )
            change_kind = "assert" if not draft.is_active else "noop"
            fact = _new_fact(
                annotation=annotation,
                chapter_id=chunk.chunk_id,
                domain="relation",
                ordinal=ordinal,
                subject=from_entity,
                predicate=str(relation_item.relation_type),
                object_value=_entity_descriptor(to_entity),
                value=None,
                participants=[
                    {"role": "from", "entity": _entity_descriptor(from_entity)},
                    {"role": "to", "entity": _entity_descriptor(to_entity)},
                ],
                content={
                    "kind": "relation",
                    "chapter_id": chunk.chunk_id,
                    "relation_id": relation_id,
                    "relation_type": str(relation_item.relation_type),
                    "change_kind": change_kind,
                },
                evidence=evidence,
            )
            facts.append(fact)
            _apply_relation_change(
                draft, fact=fact, change_kind=change_kind, relation_type=str(relation_item.relation_type)
            )
        for ordinal, foreshadowing in enumerate(chunk.foreshadowings, start=1):
            # 2026-08-22setup_event_id 直接取服务端生成的 setup_node_id
            setup_event_id = foreshadowing.setup_node_id
            facts.append(
                _new_fact(
                    annotation=annotation,
                    chapter_id=chunk.chunk_id,
                    domain="foreshadowing",
                    ordinal=ordinal,
                    subject=None,
                    predicate="其他",
                    object_value=None,
                    value={"description": foreshadowing.description, "setup_event_id": setup_event_id},
                    participants=[],
                    content={"kind": "foreshadowing", "chapter_id": chunk.chunk_id, "setup_event_id": setup_event_id},
                    evidence=evidence,
                    event_id=setup_event_id,
                )
            )
    for entity_id, changes in attribute_changes.items():
        for ordinal, change in enumerate(changes, start=1):
            entity = next((item for item in entities.values() if int(item.entity_id) == entity_id), None)
            if entity is None:
                continue
            chapter_for_fact = int(change.get("chapter_id", annotation.chapter_id))
            fact = _new_fact(
                annotation=annotation,
                chapter_id=chapter_for_fact,
                domain="entity_attribute",
                ordinal=ordinal,
                subject=entity,
                predicate=str(change["field"]),
                object_value=None,
                value=change.get("after"),
                participants=[],
                content={"kind": "entity_attribute", **change},
                evidence=_chapter_text_evidence(session, run_id=annotation.run_id, chapter_id=chapter_for_fact),
                fact_id=str(
                    uuid5(
                        UUID(annotation.annotation_id),
                        f"{chapter_for_fact}:entity_attribute:{entity_id}:{ordinal}",
                    )
                ),
                payload_path=(f"chunks/{chapter_for_fact}/entity_attribute/{entity_id}/{ordinal}"),
            )
            change["fact_id"] = fact.fact_id
            facts.append(fact)
    session.add_all(facts)
    session.flush()
    for draft in relation_drafts.values():
        _persist_relation_state(session, annotation=annotation, draft=draft)
    return facts


def _resolve_case_entity(
    session: Session,
    *,
    run_id: str,
    name: str,
    entities: dict[str, GraphEntity],
    allowed_types: tuple[str, ...],
    chapter_id: int,
) -> GraphEntity:
    """2026-08-19 用于解析案例关系端点实体"""
    entity = entities.get(_normalized_name(name))
    if entity is not None:
        if entity.entity_type not in allowed_types:
            raise ValueError(f"案例端点实体类型不符合关系约束: {name}")
        entity.last_seen_chapter = max(int(entity.last_seen_chapter), chapter_id)
        return entity
    if len(allowed_types) != 1:
        raise ValueError(f"案例端点实体未登记且大类不唯一，请先登记再解决: {name}")
    entity = GraphEntity(
        run_id=run_id,
        canonical_name=name,
        entity_type=allowed_types[0],
        tags=[],
        attributes={"entity_type": allowed_types[0]},
        first_seen_chapter=chapter_id,
        last_seen_chapter=chapter_id,
    )
    session.add(entity)
    session.flush()
    entities[_normalized_name(name)] = entity
    return entity


def _target_chapter_id(resolved_case: ResolvedCase) -> int:
    """2026-08-19 用于读取案例登记时的章节锚点"""
    chapter_id = resolved_case.target_ref.get("chunk_id")
    if chapter_id is None:
        raise ValueError(f"案例目标缺少章节 ID: {resolved_case.case_id}")
    return int(chapter_id)


def _persist_dialogue_resolution(session: Session, *, run_id: str, resolved_case: ResolvedCase) -> DialogueRecord:
    """2026-08-19 用于把 dialogue 动作更新到对话记录"""
    candidate_key = resolved_case.target_ref.get("dialogue_id") or resolved_case.target_ref.get("candidate_key")
    record = session.execute(
        select(DialogueRecord).where(
            DialogueRecord.run_id == run_id, DialogueRecord.candidate_key == str(candidate_key)
        )
    ).scalar_one_or_none()
    if record is None:
        raise ValueError(f"案例目标对话记录不存在: {resolved_case.case_id}")
    if resolved_case.speaker is not None:
        record.speaker = resolved_case.speaker
    if resolved_case.tone is not None:
        record.tone = resolved_case.tone
    if resolved_case.description is not None:
        record.content = resolved_case.description
    if resolved_case.is_inner_monologue is not None:
        record.is_inner_monologue = resolved_case.is_inner_monologue
    record.updated_at = datetime.now(UTC)
    session.flush()
    return record


def _persist_fact_resolution(
    session: Session,
    *,
    annotation: ChapterAnnotationRecord,
    boundary: ChapterBoundary,
    resolved_case: ResolvedCase,
    entities: dict[str, GraphEntity],
) -> GraphFact:
    """2026-08-19 用于把 fact 动作写成章节关系事实和状态"""
    relation_type = str(resolved_case.relation_type)
    definition = RELATION_DEFINITIONS[relation_type]
    from_entity = _resolve_case_entity(
        session,
        run_id=annotation.run_id,
        name=str(resolved_case.from_entity),
        entities=entities,
        allowed_types=tuple(definition["from_types"]),
        chapter_id=annotation.chapter_id,
    )
    to_entity = _resolve_case_entity(
        session,
        run_id=annotation.run_id,
        name=str(resolved_case.to_entity),
        entities=entities,
        allowed_types=tuple(definition["to_types"]),
        chapter_id=annotation.chapter_id,
    )
    relation_id = _relation_id(
        annotation.run_id,
        int(from_entity.entity_id),
        int(to_entity.entity_id),
        relation_type,
        str(definition["directionality"]),
    )
    relation = session.get(GraphRelation, relation_id)
    if relation is None:
        relation = GraphRelation(
            relation_id=relation_id,
            run_id=annotation.run_id,
            from_entity_id=int(from_entity.entity_id),
            to_entity_id=int(to_entity.entity_id),
            directionality=str(definition["directionality"]),
            relation_semantics=str(definition["semantics"]),
        )
        session.add(relation)
        session.flush()
    fact = GraphFact(
        run_id=annotation.run_id,
        chapter_id=annotation.chapter_id,
        fact_id=str(uuid5(NAMESPACE_URL, f"noveliq:case:{annotation.run_id}:{resolved_case.case_id}")),
        fact_type="relation",
        subject_entity_id=int(from_entity.entity_id),
        predicate=relation_type,
        object=_entity_descriptor(to_entity),
        value=None,
        participants=[
            {"role": "from", "entity": _entity_descriptor(from_entity)},
            {"role": "to", "entity": _entity_descriptor(to_entity)},
        ],
        scope=f"chapter:{annotation.chapter_id}",
        story_time=None,
        assertion="affirmed",
        confidence="high",
        content={
            "kind": "relation",
            "relation_id": relation_id,
            "relation_type": relation_type,
            "change_kind": str(resolved_case.change_kind),
            "reason": resolved_case.reason,
        },
        effective_chapter_id=annotation.chapter_id,
        source_kind="case_resolution",
        annotation_id=annotation.annotation_id,
        payload_path=f"case_resolution/{resolved_case.case_id}",
        event_id=None,
        evidence=_chapter_text_evidence(session, run_id=annotation.run_id, chapter_id=annotation.chapter_id),
    )
    session.add(fact)
    session.flush()
    draft = _relation_draft(
        session,
        run_id=annotation.run_id,
        relation=relation,
        chapter_order=boundary.chapter_order,
        relation_type=relation_type,
        current_chapter_id=annotation.chapter_id,
    )
    _apply_relation_change(draft, fact=fact, change_kind=str(resolved_case.change_kind), relation_type=relation_type)
    _persist_relation_state(session, annotation=annotation, draft=draft)
    return fact


def _persist_foreshadowing_resolution(
    session: Session,
    *,
    run_id: str,
    current_chapter_id: int,
    resolved_case: ResolvedCase,
) -> dict[str, Any]:
    """2026-08-19 用于把 foreshadowing 动作更新到伏笔线程"""
    setup_id = resolved_case.target_ref.get("setup_id")
    thread = session.get(ForeshadowingThread, str(setup_id))
    if thread is None or thread.run_id != run_id:
        raise ValueError(f"案例目标伏笔线程不存在: {resolved_case.case_id}")
    for field_name in (
        "setup_summary",
        "setup_kind",
        "expected_payoff_family",
        "payoff_likelihood",
        "confidence",
        "strength",
    ):
        value = getattr(resolved_case, field_name)
        if value is not None:
            setattr(thread, field_name, value)
    if resolved_case.setup_status is not None:
        thread.status = resolved_case.setup_status
    if resolved_case.setup_event_id is not None:
        thread.setup_event_id = resolved_case.setup_event_id
    if resolved_case.payoff_event_id is not None:
        thread.payoff_event_id = resolved_case.payoff_event_id
        thread.last_chapter_id = current_chapter_id
        thread.active = False
        thread.status = "likely_paid_off"
    thread.updated_at = datetime.now(UTC)
    session.flush()
    return {
        "thread": thread,
        "target_setup_event_id": resolved_case.setup_event_id,
        "target_payoff_event_id": resolved_case.payoff_event_id,
    }


def _persist_resolved_cases(
    session: Session,
    *,
    annotation: ChapterAnnotationRecord,
    boundary: ChapterBoundary,
    resolved_cases: list[ResolvedCase],
    authorized_text_chapter_ids: set[int],
    entities: dict[str, GraphEntity],
) -> dict[str, Any]:
    """2026-08-19 用于按案例动作分派解决并校验章节授权"""
    targets: dict[str, Any] = {}
    allowed_chapter_ids = set(authorized_text_chapter_ids) | {annotation.chapter_id}
    for resolved_case in resolved_cases:
        target_chapter_id = _target_chapter_id(resolved_case)
        if target_chapter_id not in allowed_chapter_ids:
            raise ValueError(f"resolve_case 使用了未经系统读取授权的章节: {target_chapter_id}")
        target: Any
        if resolved_case.action == "dialogue":
            target = _persist_dialogue_resolution(session, run_id=annotation.run_id, resolved_case=resolved_case)
        elif resolved_case.action == "fact":
            target = _persist_fact_resolution(
                session, annotation=annotation, boundary=boundary, resolved_case=resolved_case, entities=entities
            )
        elif resolved_case.action == "foreshadowing":
            target = _persist_foreshadowing_resolution(
                session, run_id=annotation.run_id, current_chapter_id=annotation.chapter_id, resolved_case=resolved_case
            )
        elif resolved_case.action == "close":
            target = None
        else:
            raise ValueError(f"未知案例动作: {resolved_case.action}")
        targets[resolved_case.case_id] = target
    return targets


def persist_completion_graph(
    session: Session,
    *,
    annotation: ChapterAnnotationRecord,
    resolved_cases: list[ResolvedCase],
    authorized_text_chapter_ids: set[int],
    authorized_text_paragraph_ids: set[int] | None = None,
) -> PersistedGraphResult:
    """2026-08-20 扁平化图谱持久化链，内联章节边界生成和标注校验逻辑"""
    payload = BoundChapterAnnotation.model_validate(annotation.payload)

    # 内联章节和段落查询
    chapter = session.execute(
        select(Chapter).where(Chapter.run_id == annotation.run_id, Chapter.chapter_id == annotation.chapter_id)
    ).scalar_one_or_none()
    if chapter is None or chapter.text is None:
        raise ValueError(f"章节不存在或没有正文: run_id={annotation.run_id} chapter_id={annotation.chapter_id}")

    # 内联章节边界生成
    chapters = list(
        session.execute(
            select(Chapter)
            .where(Chapter.run_id == annotation.run_id, Chapter.text.isnot(None))
            .order_by(Chapter.sequence, Chapter.chapter_id)
        ).scalars()
    )
    boundary: ChapterBoundary | None = None
    for order, ch in enumerate(chapters, start=1):
        if int(ch.chapter_id) == annotation.chapter_id:
            boundary = ChapterBoundary(
                run_id=annotation.run_id,
                chapter_id=annotation.chapter_id,
                chapter_order=order,
                first_chapter_id=annotation.chapter_id,
                last_chapter_id=annotation.chapter_id,
                annotation_id=annotation.annotation_id,
            )
            break
    if boundary is None:
        raise ValueError(f"章节不存在或没有正文: run_id={annotation.run_id} chapter_id={annotation.chapter_id}")

    # 内联标注校验
    if [chunk.chunk_id for chunk in payload.chunks] != [annotation.chapter_id]:
        raise ValueError("章节 payload chunk 顺序与数据库不一致")

    # 2026-08-22 重构：证据升为章级单份，事件节点只携带树结构；
    # 模型零结构输入后不再存在节点级锚点/哈希可校验，
    # 章级证据在持久化时按章统一盖章（_persist_event_nodes）
    _chapter_text_evidence(session, run_id=annotation.run_id, chapter_id=annotation.chapter_id)

    # 继续原有逻辑
    entities, attribute_changes = _resolve_entities(session, annotation=annotation, payload=payload)
    facts = _persist_annotation_facts(
        session,
        annotation=annotation,
        boundary=boundary,
        payload=payload,
        entities=entities,
        attribute_changes=attribute_changes,
    )
    _persist_state_rows(
        session,
        annotation=annotation,
        boundary=boundary,
        facts=facts,
        entities=entities,
        attribute_changes=attribute_changes,
    )
    session.flush()
    targets = _persist_resolved_cases(
        session,
        annotation=annotation,
        boundary=boundary,
        resolved_cases=resolved_cases,
        authorized_text_chapter_ids=authorized_text_chapter_ids,
        entities=entities,
    )
    session.flush()
    return PersistedGraphResult(chapter_boundary=boundary, resolved_targets_by_case_id=targets)
