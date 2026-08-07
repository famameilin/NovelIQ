"""
章节级事实图版本原子写入
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from src.agents.annotation.schema import (
    ChapterFinish,
    EntityType,
    Evidence,
    EvidenceList,
    PulledResult,
    TextEvidence,
)
from src.storage.models import (
    ChapterAnnotationRecord,
    Chunk,
    EntityStateVersion,
    GraphEntity,
    GraphFact,
    GraphRelation,
    GraphRelationVersion,
    GraphVersion,
)

_ENTITY_FIELDS: tuple[tuple[str, EntityType], ...] = (
    ("characters", "character"),
    ("locations", "location"),
    ("objects", "object"),
    ("organizations", "organization"),
)
_FACT_FIELDS = (
    "character_observations",
    "location_observations",
    "dialogues",
    "events",
    "relations",
    "states",
    "foreshadowings",
)
_FACT_KIND_BY_FIELD = {
    "character_observations": "character_observation",
    "location_observations": "location_observation",
    "dialogues": "dialogue",
    "events": "event",
    "relations": "relation",
    "states": "state",
    "foreshadowings": "foreshadowing",
}


@dataclass(slots=True)
class PersistedGraphResult:
    """2026-08-07 用于返回图版本和 finish pull 事实的真实持久化映射"""

    graph_version: GraphVersion
    finish_facts_by_ref: dict[str, GraphFact]
    pulled_facts_by_case_id: dict[str, GraphFact]


@dataclass(slots=True)
class _RelationDraft:
    """2026-08-07 用于在单章内汇总同一稳定关系的多次变化"""

    relation: GraphRelation
    previous_revision: int
    relation_type: str
    attributes: dict[str, Any]
    is_active: bool
    changes: list[dict[str, Any]]


def stable_annotation_fact_id(annotation_id: str, item_ref: str) -> str:
    """2026-08-07 用于按 annotation_id 与稳定标注项 ref 生成事实 ID"""
    digest = hashlib.sha256(f"{annotation_id}:{item_ref}".encode()).hexdigest()
    return f"ann_{digest}"


def _graph_version_id(run_id: str, chapter_id: int) -> str:
    """2026-08-07 用于为同一 run 章节生成事务重试稳定的图版本 ID"""
    return str(uuid5(NAMESPACE_URL, f"noveliq:graph-version:{run_id}:{chapter_id}"))


def _relation_id(run_id: str, fact_id: str) -> str:
    """2026-08-07 用于为 assert 关系事实生成事务重试稳定的关系 ID"""
    return str(uuid5(NAMESPACE_URL, f"noveliq:relation:{run_id}:{fact_id}"))


def _chapter_bounds(session: Session, run_id: str, chapter_id: int) -> tuple[int, int, int]:
    """2026-08-07 用于按具名字段读取章节顺序和首尾 chunk 边界"""
    chapter_rows = list(
        session.execute(
            select(
                Chunk.chapter_id.label("chapter_id"),
                func.min(Chunk.chunk_id).label("first_chunk_id"),
                func.max(Chunk.chunk_id).label("last_chunk_id"),
            )
            .where(Chunk.run_id == run_id)
            .group_by(Chunk.chapter_id)
            .order_by(func.min(Chunk.chunk_id))
        ).all()
    )
    for chapter_order, row in enumerate(chapter_rows, start=1):
        if int(row.chapter_id) == chapter_id:
            return chapter_order, int(row.first_chunk_id), int(row.last_chunk_id)
    raise ValueError(f"章节不存在或没有 chunk: run_id={run_id} chapter_id={chapter_id}")


def _iter_finish_evidence(finish: ChapterFinish) -> list[Evidence]:
    """2026-08-07 用于收集实体目录和全部逐 chunk 标注项 Evidence"""
    evidence_items: list[Evidence] = []
    for field_name, _entity_type in _ENTITY_FIELDS:
        for entity in getattr(finish.entities, field_name):
            evidence_items.extend(entity.evidence)
    for chunk in finish.chunks:
        for field_name in _FACT_FIELDS:
            for item in getattr(chunk, field_name):
                evidence_items.extend(item.evidence)
    return evidence_items


def _finish_fact_refs(annotation_id: str, finish: ChapterFinish) -> set[tuple[str, int]]:
    """2026-08-07 用于生成本章全部待提交事实引用以阻止自引用"""
    return {
        (stable_annotation_fact_id(annotation_id, item.ref), 1)
        for chunk in finish.chunks
        for field_name in _FACT_FIELDS
        for item in getattr(chunk, field_name)
    }


def _validate_evidence_authorization(
    session: Session,
    *,
    annotation: ChapterAnnotationRecord,
    finish: ChapterFinish,
    chapter_order: int,
    authorized_text_chunk_ids: set[int],
    visible_graph_fact_refs: set[tuple[str, int]],
) -> None:
    """2026-08-07 用于复核 finish Evidence 的同 run 授权与依赖方向"""
    pending_refs = _finish_fact_refs(annotation.annotation_id, finish)
    text_chunk_ids: set[int] = set()
    graph_fact_refs: set[tuple[str, int]] = set()
    for evidence in _iter_finish_evidence(finish):
        if isinstance(evidence, TextEvidence):
            if evidence.chunk_id not in authorized_text_chunk_ids:
                raise ValueError(
                    f"TextEvidence 未经本轮原文读取授权: chunk_id={evidence.chunk_id}"
                )
            text_chunk_ids.add(evidence.chunk_id)
            continue
        reference = (evidence.fact_id, evidence.fact_revision)
        if reference in pending_refs:
            raise ValueError(f"GraphEvidence 不允许引用本章待提交事实: {reference}")
        if reference not in visible_graph_fact_refs:
            raise ValueError(f"GraphEvidence 未由本轮图搜索授权: {reference}")
        graph_fact_refs.add(reference)

    if text_chunk_ids:
        existing_chunk_ids = set(
            session.execute(
                select(Chunk.chunk_id).where(
                    Chunk.run_id == annotation.run_id,
                    Chunk.chunk_id.in_(text_chunk_ids),
                )
            ).scalars()
        )
        missing_chunk_ids = sorted(text_chunk_ids - existing_chunk_ids)
        if missing_chunk_ids:
            raise ValueError(f"TextEvidence 引用了跨 run 或不存在的 chunk: {missing_chunk_ids}")

    if graph_fact_refs:
        rows = session.execute(
            select(
                GraphFact.fact_id.label("fact_id"),
                GraphFact.fact_revision.label("fact_revision"),
                GraphVersion.chapter_order.label("chapter_order"),
            )
            .join(GraphVersion, GraphVersion.graph_version_id == GraphFact.graph_version_id)
            .where(
                GraphFact.run_id == annotation.run_id,
                tuple_(GraphFact.fact_id, GraphFact.fact_revision).in_(graph_fact_refs),
            )
        ).all()
        existing_refs = {
            (str(row.fact_id), int(row.fact_revision))
            for row in rows
        }
        missing_refs = sorted(graph_fact_refs - existing_refs)
        if missing_refs:
            raise ValueError(f"GraphEvidence 引用了跨 run 或不存在的事实版本: {missing_refs}")
        invalid_order = [
            (str(row.fact_id), int(row.fact_revision))
            for row in rows
            if int(row.chapter_order) >= chapter_order
        ]
        if invalid_order:
            raise ValueError(f"GraphEvidence 只能引用前序章节事实版本: {invalid_order}")


def _entity_attributes(entity: Any, entity_type: EntityType) -> dict[str, Any]:
    """2026-08-07 用于提取不同实体类型的目录扩展属性"""
    payload = entity.model_dump(mode="json")
    common_fields = {
        "ref",
        "name",
        "existing_entity_id",
        "mentions",
        "confidence",
        "evidence",
    }
    return {
        key: value
        for key, value in payload.items()
        if key not in common_fields and value is not None
    } | {"entity_type": entity_type}


def _resolve_entity_directory(
    session: Session,
    *,
    annotation: ChapterAnnotationRecord,
    finish: ChapterFinish,
    visible_graph_entity_ids: set[int],
) -> tuple[dict[str, GraphEntity], dict[int, GraphEntity]]:
    """2026-08-07 用于先解析实体目录并显式创建或匹配四类图节点"""
    entities_by_ref: dict[str, GraphEntity] = {}
    entities_by_id: dict[int, GraphEntity] = {}
    for field_name, entity_type in _ENTITY_FIELDS:
        for entity_item in getattr(finish.entities, field_name):
            first_seen_chunk = min(mention.chunk_id for mention in entity_item.mentions)
            last_seen_chunk = max(mention.chunk_id for mention in entity_item.mentions)
            attributes = _entity_attributes(entity_item, entity_type)
            if entity_item.existing_entity_id is not None:
                if entity_item.existing_entity_id not in visible_graph_entity_ids:
                    raise ValueError(
                        "existing_entity_id 未由本轮图搜索授权: "
                        f"{entity_item.existing_entity_id}"
                    )
                entity = session.get(GraphEntity, entity_item.existing_entity_id)
                if entity is None or entity.run_id != annotation.run_id:
                    raise ValueError(
                        "existing_entity_id 不存在或跨 run: "
                        f"{entity_item.existing_entity_id}"
                    )
                if entity.entity_type != entity_type:
                    raise ValueError(
                        f"existing_entity_id 类型不一致: id={entity.entity_id} "
                        f"expected={entity_type} actual={entity.entity_type}"
                    )
                entity.first_seen_chunk = min(entity.first_seen_chunk, first_seen_chunk)
                entity.last_seen_chunk = max(entity.last_seen_chunk, last_seen_chunk)
                entity.attributes = {**dict(entity.attributes or {}), **attributes}
            else:
                duplicate = session.execute(
                    select(GraphEntity).where(
                        GraphEntity.run_id == annotation.run_id,
                        GraphEntity.canonical_name == entity_item.name,
                    )
                ).scalar_one_or_none()
                if duplicate is not None:
                    raise ValueError(
                        "新实体名称已存在，必须使用 search_graph 返回的 existing_entity_id: "
                        f"{entity_item.name}"
                    )
                entity = GraphEntity(
                    run_id=annotation.run_id,
                    canonical_name=entity_item.name,
                    entity_type=entity_type,
                    attributes=attributes,
                    first_seen_chunk=first_seen_chunk,
                    last_seen_chunk=last_seen_chunk,
                )
                session.add(entity)
                session.flush()
            entities_by_ref[entity_item.ref] = entity
            entities_by_id[int(entity.entity_id)] = entity
    return entities_by_ref, entities_by_id


def _load_authorized_entity(
    session: Session,
    *,
    run_id: str,
    entity_id: int,
    visible_graph_entity_ids: set[int],
    cache: dict[int, GraphEntity],
    chunk_id: int,
) -> GraphEntity:
    """2026-08-07 用于按授权 existing_entity_id 读取并维护出现边界"""
    if entity_id not in visible_graph_entity_ids:
        raise ValueError(f"existing_entity_id 未由本轮图搜索授权: {entity_id}")
    entity = cache.get(entity_id) or session.get(GraphEntity, entity_id)
    if entity is None or entity.run_id != run_id:
        raise ValueError(f"existing_entity_id 不存在或跨 run: {entity_id}")
    entity.last_seen_chunk = max(entity.last_seen_chunk, chunk_id)
    cache[entity_id] = entity
    return entity


def _resolve_endpoint(
    session: Session,
    *,
    run_id: str,
    ref: str | None,
    existing_entity_id: int | None,
    entities_by_ref: dict[str, GraphEntity],
    entities_by_id: dict[int, GraphEntity],
    visible_graph_entity_ids: set[int],
    chunk_id: int,
) -> GraphEntity | None:
    """2026-08-07 用于把 finish 内部 ref 或授权既有 ID 解析为图实体"""
    if ref is not None:
        entity = entities_by_ref.get(ref)
        if entity is None:
            raise ValueError(f"实体 ref 不存在: {ref}")
        entity.last_seen_chunk = max(entity.last_seen_chunk, chunk_id)
        return entity
    if existing_entity_id is not None:
        return _load_authorized_entity(
            session,
            run_id=run_id,
            entity_id=existing_entity_id,
            visible_graph_entity_ids=visible_graph_entity_ids,
            cache=entities_by_id,
            chunk_id=chunk_id,
        )
    return None


def _entity_descriptor(entity: GraphEntity | None) -> dict[str, Any] | None:
    """2026-08-07 用于把已解析实体转换为事实内容中的稳定描述"""
    if entity is None:
        return None
    return {
        "entity_id": int(entity.entity_id),
        "name": str(entity.canonical_name),
        "entity_type": str(entity.entity_type),
    }


def _new_graph_fact(
    *,
    graph_version: GraphVersion,
    annotation: ChapterAnnotationRecord,
    item_ref: str,
    kind: str,
    chunk_id: int,
    subject: GraphEntity | None,
    predicate: str,
    object_value: dict[str, Any] | None,
    value: Any | None,
    participants: list[dict[str, Any]],
    story_time: dict[str, Any] | None,
    assertion: str,
    confidence: str,
    content: dict[str, Any],
    evidence: EvidenceList,
) -> GraphFact:
    """2026-08-07 用于从稳定标注项 ref 构造单个 chapter_finish 事实版本"""
    return GraphFact(
        graph_version_id=graph_version.graph_version_id,
        run_id=annotation.run_id,
        chapter_id=annotation.chapter_id,
        fact_id=stable_annotation_fact_id(annotation.annotation_id, item_ref),
        fact_revision=1,
        fact_type=kind,
        subject_entity_id=subject.entity_id if subject is not None else None,
        predicate=predicate,
        object=object_value,
        value=value,
        participants=participants,
        scope=f"chapter:{annotation.chapter_id}:chunk:{chunk_id}",
        story_time=story_time,
        assertion=assertion,
        confidence=confidence,
        content=content,
        evidence=evidence.model_dump(mode="json"),
        effective_chunk_id=chunk_id,
        source_kind="chapter_finish",
        annotation_id=annotation.annotation_id,
        payload_path=f"chunks/{chunk_id}/{kind}/{item_ref}",
    )


def _persist_finish_facts(
    session: Session,
    *,
    annotation: ChapterAnnotationRecord,
    finish: ChapterFinish,
    graph_version: GraphVersion,
    entities_by_ref: dict[str, GraphEntity],
    entities_by_id: dict[int, GraphEntity],
    visible_graph_entity_ids: set[int],
) -> dict[str, GraphFact]:
    """2026-08-07 用于按 chunk 顺序解析观察对话事件关系状态和伏笔事实"""
    rows_by_ref: dict[str, GraphFact] = {}

    def endpoint(
        *,
        ref: str | None,
        existing_entity_id: int | None,
        chunk_id: int,
    ) -> GraphEntity | None:
        """2026-08-07 用于在逐 chunk 事实转换中解析实体端点"""
        return _resolve_endpoint(
            session,
            run_id=annotation.run_id,
            ref=ref,
            existing_entity_id=existing_entity_id,
            entities_by_ref=entities_by_ref,
            entities_by_id=entities_by_id,
            visible_graph_entity_ids=visible_graph_entity_ids,
            chunk_id=chunk_id,
        )

    for chunk in finish.chunks:
        chunk_id = chunk.chunk_id
        for character_observation in chunk.character_observations:
            entity = endpoint(
                ref=character_observation.entity_ref,
                existing_entity_id=character_observation.entity_existing_entity_id,
                chunk_id=chunk_id,
            )
            content = {
                "kind": "character_observation",
                "ref": character_observation.ref,
                "chunk_id": chunk_id,
                "entity": _entity_descriptor(entity),
                "role_function": character_observation.role_function,
                "action": character_observation.action,
                "action_type": character_observation.action_type,
                "emotion": character_observation.emotion,
            }
            row = _new_graph_fact(
                graph_version=graph_version,
                annotation=annotation,
                item_ref=character_observation.ref,
                kind="character_observation",
                chunk_id=chunk_id,
                subject=entity,
                predicate=character_observation.action_type,
                object_value=None,
                value={
                    "role_function": character_observation.role_function,
                    "action": character_observation.action,
                    "emotion": character_observation.emotion,
                },
                participants=[],
                story_time=None,
                assertion="affirmed",
                confidence=character_observation.confidence,
                content=content,
                evidence=character_observation.evidence,
            )
            session.add(row)
            rows_by_ref[character_observation.ref] = row

        for location_observation in chunk.location_observations:
            location = endpoint(
                ref=location_observation.location_ref,
                existing_entity_id=location_observation.location_existing_entity_id,
                chunk_id=chunk_id,
            )
            content = {
                "kind": "location_observation",
                "ref": location_observation.ref,
                "chunk_id": chunk_id,
                "location": _entity_descriptor(location),
                "predicate": location_observation.predicate,
                "value": location_observation.value,
            }
            row = _new_graph_fact(
                graph_version=graph_version,
                annotation=annotation,
                item_ref=location_observation.ref,
                kind="location_observation",
                chunk_id=chunk_id,
                subject=location,
                predicate=location_observation.predicate,
                object_value=None,
                value=location_observation.value,
                participants=[],
                story_time=(
                    location_observation.story_time.model_dump(mode="json")
                    if location_observation.story_time is not None
                    else None
                ),
                assertion="affirmed",
                confidence=location_observation.confidence,
                content=content,
                evidence=location_observation.evidence,
            )
            session.add(row)
            rows_by_ref[location_observation.ref] = row

        for dialogue in chunk.dialogues:
            speaker = endpoint(
                ref=dialogue.speaker_ref,
                existing_entity_id=dialogue.speaker_existing_entity_id,
                chunk_id=chunk_id,
            )
            content = {
                "kind": "dialogue",
                "ref": dialogue.ref,
                "chunk_id": chunk_id,
                "content": dialogue.content,
                "start": dialogue.start,
                "end": dialogue.end,
                "speaker": _entity_descriptor(speaker),
                "tone": dialogue.tone,
                "is_inner_monologue": dialogue.is_inner_monologue,
            }
            row = _new_graph_fact(
                graph_version=graph_version,
                annotation=annotation,
                item_ref=dialogue.ref,
                kind="dialogue",
                chunk_id=chunk_id,
                subject=speaker,
                predicate="spoke",
                object_value=None,
                value={
                    "content": dialogue.content,
                    "start": dialogue.start,
                    "end": dialogue.end,
                    "tone": dialogue.tone,
                    "is_inner_monologue": dialogue.is_inner_monologue,
                },
                participants=(
                    [{"role": "speaker", "entity": _entity_descriptor(speaker)}]
                    if speaker is not None
                    else []
                ),
                story_time=None,
                assertion="affirmed",
                confidence=dialogue.confidence,
                content=content,
                evidence=dialogue.evidence,
            )
            session.add(row)
            rows_by_ref[dialogue.ref] = row

        for event in chunk.events:
            resolved_participants: list[dict[str, Any]] = []
            participant_entities: list[GraphEntity] = []
            for participant in event.participants:
                entity = endpoint(
                    ref=participant.entity_ref,
                    existing_entity_id=participant.entity_existing_entity_id,
                    chunk_id=chunk_id,
                )
                if entity is None:
                    raise ValueError(f"event participant 缺少实体: {event.ref}")
                participant_entities.append(entity)
                resolved_participants.append(
                    {
                        "role": participant.role,
                        "entity": _entity_descriptor(entity),
                    }
                )
            location = endpoint(
                ref=event.location_ref,
                existing_entity_id=event.location_existing_entity_id,
                chunk_id=chunk_id,
            )
            content = {
                "kind": "event",
                "ref": event.ref,
                "chunk_id": chunk_id,
                "event_type": event.event_type,
                "summary": event.summary,
                "participants": resolved_participants,
                "location": _entity_descriptor(location),
            }
            row = _new_graph_fact(
                graph_version=graph_version,
                annotation=annotation,
                item_ref=event.ref,
                kind="event",
                chunk_id=chunk_id,
                subject=participant_entities[0] if participant_entities else None,
                predicate=event.event_type,
                object_value=_entity_descriptor(location),
                value={"summary": event.summary},
                participants=resolved_participants,
                story_time=(
                    event.story_time.model_dump(mode="json")
                    if event.story_time is not None
                    else None
                ),
                assertion="affirmed",
                confidence=event.confidence,
                content=content,
                evidence=event.evidence,
            )
            session.add(row)
            rows_by_ref[event.ref] = row

        for relation in chunk.relations:
            from_entity = endpoint(
                ref=relation.from_ref,
                existing_entity_id=relation.from_existing_entity_id,
                chunk_id=chunk_id,
            )
            to_entity = endpoint(
                ref=relation.to_ref,
                existing_entity_id=relation.to_existing_entity_id,
                chunk_id=chunk_id,
            )
            representative = endpoint(
                ref=relation.representative_ref,
                existing_entity_id=relation.representative_existing_entity_id,
                chunk_id=chunk_id,
            )
            if from_entity is None or to_entity is None:
                raise ValueError(f"relation 端点缺失: {relation.ref}")
            fact_id = stable_annotation_fact_id(annotation.annotation_id, relation.ref)
            relation_id = relation.relation_id or _relation_id(annotation.run_id, fact_id)
            content = {
                "kind": "relation",
                "ref": relation.ref,
                "chunk_id": chunk_id,
                "from_entity": _entity_descriptor(from_entity),
                "to_entity": _entity_descriptor(to_entity),
                "relation_type": relation.relation_type,
                "change_kind": relation.change_kind,
                "relation_id": relation_id,
                "directionality": relation.directionality,
                "relation_semantics": relation.relation_semantics,
                "representative_entity_id": (
                    int(representative.entity_id)
                    if representative is not None
                    else None
                ),
            }
            row = _new_graph_fact(
                graph_version=graph_version,
                annotation=annotation,
                item_ref=relation.ref,
                kind="relation",
                chunk_id=chunk_id,
                subject=from_entity,
                predicate=relation.relation_type,
                object_value=_entity_descriptor(to_entity),
                value=None,
                participants=[
                    {"role": "from", "entity": _entity_descriptor(from_entity)},
                    {"role": "to", "entity": _entity_descriptor(to_entity)},
                ],
                story_time=None,
                assertion="affirmed",
                confidence=relation.confidence,
                content=content,
                evidence=relation.evidence,
            )
            session.add(row)
            rows_by_ref[relation.ref] = row

        for state in chunk.states:
            entity = endpoint(
                ref=state.entity_ref,
                existing_entity_id=state.entity_existing_entity_id,
                chunk_id=chunk_id,
            )
            object_entity = endpoint(
                ref=state.object_ref,
                existing_entity_id=state.object_existing_entity_id,
                chunk_id=chunk_id,
            )
            content = {
                "kind": "state",
                "ref": state.ref,
                "chunk_id": chunk_id,
                "entity": _entity_descriptor(entity),
                "predicate": state.predicate,
                "object": _entity_descriptor(object_entity),
                "value": state.value,
                "assertion": state.assertion,
            }
            row = _new_graph_fact(
                graph_version=graph_version,
                annotation=annotation,
                item_ref=state.ref,
                kind="state",
                chunk_id=chunk_id,
                subject=entity,
                predicate=state.predicate,
                object_value=_entity_descriptor(object_entity),
                value=state.value,
                participants=[],
                story_time=(
                    state.story_time.model_dump(mode="json")
                    if state.story_time is not None
                    else None
                ),
                assertion=state.assertion,
                confidence=state.confidence,
                content=content,
                evidence=state.evidence,
            )
            session.add(row)
            rows_by_ref[state.ref] = row

        for foreshadowing in chunk.foreshadowings:
            content = {
                "kind": "foreshadowing",
                "ref": foreshadowing.ref,
                "chunk_id": chunk_id,
                **foreshadowing.model_dump(mode="json", exclude={"evidence", "ref", "confidence"}),
            }
            row = _new_graph_fact(
                graph_version=graph_version,
                annotation=annotation,
                item_ref=foreshadowing.ref,
                kind="foreshadowing",
                chunk_id=chunk_id,
                subject=None,
                predicate=foreshadowing.setup_kind,
                object_value=None,
                value={
                    "setup_summary": foreshadowing.setup_summary,
                    "expected_payoff_family": foreshadowing.expected_payoff_family,
                    "payoff_likelihood": foreshadowing.payoff_likelihood,
                    "setup_status": foreshadowing.setup_status,
                },
                participants=[],
                story_time=None,
                assertion="affirmed",
                confidence=foreshadowing.confidence,
                content=content,
                evidence=foreshadowing.evidence,
            )
            session.add(row)
            rows_by_ref[foreshadowing.ref] = row

    session.flush()
    return rows_by_ref


def _previous_entity_state(
    session: Session,
    *,
    run_id: str,
    entity_id: int,
    chapter_order: int,
) -> tuple[int, dict[str, Any]]:
    """2026-08-07 用于读取目标章节之前最近的实体完整状态"""
    row = session.execute(
        select(EntityStateVersion)
        .join(GraphVersion, GraphVersion.graph_version_id == EntityStateVersion.graph_version_id)
        .where(
            EntityStateVersion.run_id == run_id,
            EntityStateVersion.entity_id == entity_id,
            GraphVersion.chapter_order < chapter_order,
        )
        .order_by(GraphVersion.chapter_order.desc(), EntityStateVersion.state_revision.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return 0, {}
    return int(row.state_revision), dict(row.state)


def _state_updates(fact: GraphFact) -> dict[str, Any]:
    """2026-08-07 用于把观察和状态事实转换为实体状态字段更新"""
    content = dict(fact.content)
    kind = content.get("kind")
    if kind == "character_observation":
        return {
            "role_function": content["role_function"],
            "action": content["action"],
            "action_type": content["action_type"],
            "emotion": content["emotion"],
        }
    if kind == "location_observation":
        return {fact.predicate: fact.value}
    if kind == "state":
        next_value: Any = fact.object if fact.object is not None else fact.value
        return {fact.predicate: next_value if fact.assertion == "affirmed" else None}
    return {}


def _persist_state_versions(
    session: Session,
    *,
    graph_version: GraphVersion,
    chapter_order: int,
    facts: list[GraphFact],
) -> None:
    """2026-08-07 用于汇总同一实体本章多次观察和状态变化"""
    state_by_entity: dict[int, dict[str, Any]] = {}
    revision_by_entity: dict[int, int] = {}
    changes_by_entity: dict[int, list[dict[str, Any]]] = {}
    for fact in facts:
        if fact.subject_entity_id is None:
            continue
        updates = _state_updates(fact)
        if not updates:
            continue
        entity_id = int(fact.subject_entity_id)
        if entity_id not in state_by_entity:
            previous_revision, previous_state = _previous_entity_state(
                session,
                run_id=graph_version.run_id,
                entity_id=entity_id,
                chapter_order=chapter_order,
            )
            revision_by_entity[entity_id] = previous_revision
            state_by_entity[entity_id] = previous_state
            changes_by_entity[entity_id] = []
        state = state_by_entity[entity_id]
        for field_name, after in updates.items():
            before = state.get(field_name)
            if before == after:
                continue
            if after is None:
                state.pop(field_name, None)
            else:
                state[field_name] = after
            changes_by_entity[entity_id].append(
                {
                    "field": field_name,
                    "before": before,
                    "after": after,
                    "fact_id": fact.fact_id,
                    "fact_revision": fact.fact_revision,
                    "chunk_id": fact.effective_chunk_id,
                }
            )

    for entity_id, changes in changes_by_entity.items():
        if not changes:
            continue
        session.add(
            EntityStateVersion(
                graph_version_id=graph_version.graph_version_id,
                run_id=graph_version.run_id,
                chapter_id=graph_version.chapter_id,
                entity_id=entity_id,
                state_revision=revision_by_entity[entity_id] + 1,
                state=state_by_entity[entity_id],
                changes=changes,
            )
        )


def _relation_key(
    from_entity_id: int,
    to_entity_id: int,
    *,
    directionality: str,
    relation_semantics: str,
    relation_type: str,
) -> tuple[int, int, str, str, str]:
    """2026-08-07 用于生成等价活动关系的稳定比较键"""
    left_id, right_id = from_entity_id, to_entity_id
    if directionality == "bidirectional" and left_id > right_id:
        left_id, right_id = right_id, left_id
    return left_id, right_id, directionality, relation_semantics, relation_type


def _previous_relation_draft(
    session: Session,
    *,
    run_id: str,
    relation_id: str,
    chapter_order: int,
) -> _RelationDraft:
    """2026-08-07 用于读取目标章节之前最近的稳定关系版本"""
    relation = session.get(GraphRelation, relation_id)
    if relation is None or relation.run_id != run_id:
        raise ValueError(f"relation_id 不存在或跨 run: {relation_id}")
    version = session.execute(
        select(GraphRelationVersion)
        .join(GraphVersion, GraphVersion.graph_version_id == GraphRelationVersion.graph_version_id)
        .where(
            GraphRelationVersion.run_id == run_id,
            GraphRelationVersion.relation_id == relation_id,
            GraphVersion.chapter_order < chapter_order,
        )
        .order_by(GraphVersion.chapter_order.desc(), GraphRelationVersion.relation_revision.desc())
        .limit(1)
    ).scalar_one_or_none()
    if version is None:
        raise ValueError(f"relation_id 在上一章节图版本不可见: {relation_id}")
    return _RelationDraft(
        relation=relation,
        previous_revision=int(version.relation_revision),
        relation_type=str(version.relation_type),
        attributes=dict(version.attributes),
        is_active=bool(version.is_active),
        changes=[],
    )


def _active_relation_keys(
    session: Session,
    *,
    run_id: str,
    chapter_order: int,
) -> dict[tuple[int, int, str, str, str], str]:
    """2026-08-07 用于读取上一章节边界的全部等价活动关系键"""
    rows = session.execute(
        select(GraphRelationVersion, GraphRelation)
        .join(GraphRelation, GraphRelation.relation_id == GraphRelationVersion.relation_id)
        .join(GraphVersion, GraphVersion.graph_version_id == GraphRelationVersion.graph_version_id)
        .where(
            GraphRelationVersion.run_id == run_id,
            GraphVersion.chapter_order < chapter_order,
        )
        .order_by(
            GraphRelationVersion.relation_id,
            GraphVersion.chapter_order.desc(),
            GraphRelationVersion.relation_revision.desc(),
        )
    ).all()
    latest: dict[str, tuple[GraphRelationVersion, GraphRelation]] = {}
    for version, relation in rows:
        latest.setdefault(str(relation.relation_id), (version, relation))
    keys: dict[tuple[int, int, str, str, str], str] = {}
    for version, relation in latest.values():
        if not version.is_active:
            continue
        key = _relation_key(
            int(relation.from_entity_id),
            int(relation.to_entity_id),
            directionality=str(relation.directionality),
            relation_semantics=str(relation.relation_semantics),
            relation_type=str(version.relation_type),
        )
        keys[key] = str(relation.relation_id)
    return keys


def _apply_relation_change(
    *,
    draft: _RelationDraft,
    fact: GraphFact,
    change_kind: str,
    relation_type: str,
) -> None:
    """2026-08-07 用于在关系草稿上应用强化弱化修订取代或断裂"""
    before = {
        "relation_type": draft.relation_type,
        "attributes": dict(draft.attributes),
        "is_active": draft.is_active,
    }
    if change_kind == "assert":
        draft.relation_type = relation_type
        draft.is_active = True
        draft.attributes.setdefault("support_count", 1)
    elif change_kind == "reinforce":
        draft.is_active = True
        draft.attributes["support_count"] = int(draft.attributes.get("support_count", 1)) + 1
    elif change_kind == "weaken":
        draft.attributes["strength"] = int(draft.attributes.get("strength", 0)) - 1
    elif change_kind in {"refine", "supersede"}:
        draft.relation_type = relation_type
        draft.is_active = True
    elif change_kind in {"break", "retract"}:
        draft.is_active = False
    else:
        raise ValueError(f"不支持的关系变化类型: {change_kind}")
    after = {
        "relation_type": draft.relation_type,
        "attributes": dict(draft.attributes),
        "is_active": draft.is_active,
    }
    draft.changes.append(
        {
            "change_kind": change_kind,
            "before": before,
            "after": after,
            "fact_id": fact.fact_id,
            "fact_revision": fact.fact_revision,
            "chunk_id": fact.effective_chunk_id,
        }
    )


def _relation_endpoints_match(
    relation: GraphRelation,
    *,
    from_entity_id: int,
    to_entity_id: int,
) -> bool:
    """2026-08-07 用于校验关系变化仍指向同一稳定端点"""
    if relation.directionality == "bidirectional":
        return {int(relation.from_entity_id), int(relation.to_entity_id)} == {
            from_entity_id,
            to_entity_id,
        }
    return (
        int(relation.from_entity_id) == from_entity_id
        and int(relation.to_entity_id) == to_entity_id
    )


def _persist_relation_versions(
    session: Session,
    *,
    graph_version: GraphVersion,
    chapter_order: int,
    facts: list[GraphFact],
    visible_relation_ids: set[str],
) -> None:
    """2026-08-07 用于汇总稳定 relation ref 形成的本章关系版本"""
    active_keys = _active_relation_keys(
        session,
        run_id=graph_version.run_id,
        chapter_order=chapter_order,
    )
    drafts: dict[str, _RelationDraft] = {}
    for fact in facts:
        content = dict(fact.content)
        if content.get("kind") != "relation":
            continue
        if fact.subject_entity_id is None or not isinstance(fact.object, dict):
            raise ValueError(f"relation 事实缺少已解析端点: {fact.fact_id}")
        from_entity_id = int(fact.subject_entity_id)
        to_entity_id = int(fact.object["entity_id"])
        directionality = str(content["directionality"])
        relation_semantics = str(content["relation_semantics"])
        relation_type = str(content["relation_type"])
        change_kind = str(content["change_kind"])
        relation_id = str(content["relation_id"])

        if change_kind == "assert":
            key = _relation_key(
                from_entity_id,
                to_entity_id,
                directionality=directionality,
                relation_semantics=relation_semantics,
                relation_type=relation_type,
            )
            if key in active_keys:
                raise ValueError(
                    "等价活动关系已存在，必须使用 reinforce 或 refine: "
                    f"relation_id={active_keys[key]}"
                )
            relation = GraphRelation(
                relation_id=relation_id,
                run_id=graph_version.run_id,
                from_entity_id=from_entity_id,
                to_entity_id=to_entity_id,
                directionality=directionality,
                relation_semantics=relation_semantics,
            )
            session.add(relation)
            session.flush()
            attributes: dict[str, Any] = {}
            representative_entity_id = content.get("representative_entity_id")
            if representative_entity_id is not None:
                attributes["representative_entity_id"] = int(representative_entity_id)
            draft = _RelationDraft(
                relation=relation,
                previous_revision=0,
                relation_type=relation_type,
                attributes=attributes,
                is_active=False,
                changes=[],
            )
            drafts[relation_id] = draft
            active_keys[key] = relation_id
        else:
            if relation_id not in visible_relation_ids:
                raise ValueError(
                    f"关系变化引用了本轮图搜索不可见的 relation_id: {relation_id}"
                )
            existing_draft = drafts.get(relation_id)
            if existing_draft is None:
                existing_draft = _previous_relation_draft(
                    session,
                    run_id=graph_version.run_id,
                    relation_id=relation_id,
                    chapter_order=chapter_order,
                )
                drafts[relation_id] = existing_draft
            draft = existing_draft
            if not _relation_endpoints_match(
                draft.relation,
                from_entity_id=from_entity_id,
                to_entity_id=to_entity_id,
            ):
                raise ValueError(f"relation_id 的稳定端点与本次变化不一致: {relation_id}")
            if (
                str(draft.relation.directionality) != directionality
                or str(draft.relation.relation_semantics) != relation_semantics
            ):
                raise ValueError(f"relation_id 的方向或关系语义不可变: {relation_id}")

        _apply_relation_change(
            draft=draft,
            fact=fact,
            change_kind=change_kind,
            relation_type=relation_type,
        )

    for relation_id, draft in drafts.items():
        session.add(
            GraphRelationVersion(
                graph_version_id=graph_version.graph_version_id,
                run_id=graph_version.run_id,
                chapter_id=graph_version.chapter_id,
                relation_id=relation_id,
                relation_revision=draft.previous_revision + 1,
                relation_type=draft.relation_type,
                attributes=draft.attributes,
                is_active=draft.is_active,
                changes=draft.changes,
            )
        )


def _resolution_speaker_entity(
    session: Session,
    *,
    run_id: str,
    pulled_result: PulledResult,
    entities_by_ref: dict[str, GraphEntity],
) -> GraphEntity:
    """2026-08-07 用于把 dialogue_speaker resolution 映射为人物图节点"""
    speaker_name = pulled_result.resolution.speaker.name
    for candidate_entity in entities_by_ref.values():
        if candidate_entity.entity_type == "character" and candidate_entity.canonical_name == speaker_name:
            return candidate_entity
    existing_entity = session.execute(
        select(GraphEntity).where(
            GraphEntity.run_id == run_id,
            GraphEntity.canonical_name == speaker_name,
        )
    ).scalar_one_or_none()
    evidence_chunk_id = pulled_result.resolution.evidence_chunkid
    if existing_entity is None:
        new_entity = GraphEntity(
            run_id=run_id,
            canonical_name=speaker_name,
            entity_type="character",
            attributes={},
            first_seen_chunk=evidence_chunk_id,
            last_seen_chunk=evidence_chunk_id,
        )
        session.add(new_entity)
        session.flush()
        return new_entity
    if existing_entity.entity_type != "character":
        raise ValueError(f"pull resolution speaker 名称已属于非人物节点: {speaker_name}")
    existing_entity.last_seen_chunk = max(existing_entity.last_seen_chunk, evidence_chunk_id)
    return existing_entity


def _validate_case_target(target: GraphFact, pulled_result: PulledResult) -> None:
    """2026-08-07 用于核对案例内部目标仍精确指向原历史对话事实"""
    target_ref = pulled_result.target_ref
    content = dict(target.content)
    if content.get("kind") != "dialogue" or target.fact_type != "dialogue":
        raise ValueError(f"dialogue_speaker 案例目标不是对话事实: {pulled_result.case_id}")
    expected_fields = {
        "item_ref": content.get("ref"),
        "chunk_id": target.effective_chunk_id,
        "start": content.get("start"),
        "end": content.get("end"),
        "text": content.get("content"),
    }
    for field_name, expected in expected_fields.items():
        if target_ref.get(field_name) != expected:
            raise ValueError(
                f"案例目标字段与历史对话不一致: case_id={pulled_result.case_id} "
                f"field={field_name}"
            )
    if content.get("speaker") is not None:
        raise ValueError(f"案例目标对话已经具有说话人: {pulled_result.case_id}")


def _next_fact_revision(session: Session, run_id: str, fact_id: str) -> int:
    """2026-08-07 用于读取同一事实下一条不可变修订号"""
    revision = session.execute(
        select(func.max(GraphFact.fact_revision)).where(
            GraphFact.run_id == run_id,
            GraphFact.fact_id == fact_id,
        )
    ).scalar_one()
    return int(revision or 0) + 1


def _persist_pulled_results(
    session: Session,
    *,
    annotation: ChapterAnnotationRecord,
    graph_version: GraphVersion,
    pulled_results: list[PulledResult],
    authorized_text_chunk_ids: set[int],
    entities_by_ref: dict[str, GraphEntity],
) -> dict[str, GraphFact]:
    """2026-08-07 用于把 pull resolution 写成同一新图版本中的历史事实修订"""
    rows_by_case_id: dict[str, GraphFact] = {}
    for pulled_result in pulled_results:
        evidence_chunk_id = pulled_result.resolution.evidence_chunkid
        if evidence_chunk_id not in authorized_text_chunk_ids:
            raise ValueError(
                f"pull evidence_chunkid 未经本轮原文授权: {evidence_chunk_id}"
            )
        target_fact_id = str(pulled_result.target_ref.get("fact_id") or "")
        target_fact_revision = pulled_result.target_ref.get("fact_revision")
        if not target_fact_id or not isinstance(target_fact_revision, int):
            raise ValueError(
                f"案例缺少历史目标 fact_id/fact_revision: {pulled_result.case_id}"
            )
        target = session.execute(
            select(GraphFact).where(
                GraphFact.run_id == annotation.run_id,
                GraphFact.fact_id == target_fact_id,
                GraphFact.fact_revision == target_fact_revision,
            )
        ).scalar_one_or_none()
        if target is None:
            raise ValueError(f"案例目标事实不存在或跨 run: {pulled_result.case_id}")
        _validate_case_target(target, pulled_result)
        speaker = _resolution_speaker_entity(
            session,
            run_id=annotation.run_id,
            pulled_result=pulled_result,
            entities_by_ref=entities_by_ref,
        )
        speaker_descriptor = _entity_descriptor(speaker)
        content = dict(target.content)
        content["speaker"] = speaker_descriptor
        content["resolved_by_case_id"] = pulled_result.case_id
        evidence = EvidenceList.model_validate(
            [
                *list(target.evidence),
                TextEvidence(
                    reason=f"案例 {pulled_result.case_id} 的说话人已由后续原文确认",
                    chunk_id=evidence_chunk_id,
                ).model_dump(mode="json"),
            ]
        )
        row = GraphFact(
            graph_version_id=graph_version.graph_version_id,
            run_id=annotation.run_id,
            chapter_id=annotation.chapter_id,
            fact_id=target.fact_id,
            fact_revision=_next_fact_revision(
                session,
                annotation.run_id,
                target.fact_id,
            ),
            fact_type=target.fact_type,
            subject_entity_id=speaker.entity_id,
            predicate=target.predicate,
            object=target.object,
            value=target.value,
            participants=[{"role": "speaker", "entity": speaker_descriptor}],
            scope=target.scope,
            story_time=target.story_time,
            assertion=target.assertion,
            confidence=target.confidence,
            content=content,
            evidence=evidence.model_dump(mode="json"),
            effective_chunk_id=target.effective_chunk_id,
            source_kind="case_resolution",
            annotation_id=annotation.annotation_id,
            payload_path=f"case_resolution/{pulled_result.case_id}",
        )
        session.add(row)
        session.flush()
        rows_by_case_id[pulled_result.case_id] = row
    return rows_by_case_id


def persist_completion_graph(
    session: Session,
    *,
    annotation: ChapterAnnotationRecord,
    pulled_results: list[PulledResult],
    authorized_text_chunk_ids: set[int],
    visible_graph_fact_refs: set[tuple[str, int]],
    visible_relation_ids: set[str],
    visible_graph_entity_ids: set[int],
) -> PersistedGraphResult:
    """2026-08-07 用于在一个图版本中写入最终 finish 和全部 pull 修订"""
    finish = ChapterFinish.model_validate(annotation.payload)
    chapter_order, first_chunk_id, last_chunk_id = _chapter_bounds(
        session,
        annotation.run_id,
        annotation.chapter_id,
    )
    _validate_evidence_authorization(
        session,
        annotation=annotation,
        finish=finish,
        chapter_order=chapter_order,
        authorized_text_chunk_ids=authorized_text_chunk_ids,
        visible_graph_fact_refs=visible_graph_fact_refs,
    )
    graph_version = GraphVersion(
        graph_version_id=_graph_version_id(annotation.run_id, annotation.chapter_id),
        run_id=annotation.run_id,
        chapter_id=annotation.chapter_id,
        chapter_order=chapter_order,
        first_chunk_id=first_chunk_id,
        last_chunk_id=last_chunk_id,
        annotation_id=annotation.annotation_id,
    )
    session.add(graph_version)
    session.flush()

    entities_by_ref, entities_by_id = _resolve_entity_directory(
        session,
        annotation=annotation,
        finish=finish,
        visible_graph_entity_ids=visible_graph_entity_ids,
    )
    finish_facts_by_ref = _persist_finish_facts(
        session,
        annotation=annotation,
        finish=finish,
        graph_version=graph_version,
        entities_by_ref=entities_by_ref,
        entities_by_id=entities_by_id,
        visible_graph_entity_ids=visible_graph_entity_ids,
    )
    finish_fact_rows = list(finish_facts_by_ref.values())
    _persist_state_versions(
        session,
        graph_version=graph_version,
        chapter_order=chapter_order,
        facts=finish_fact_rows,
    )
    _persist_relation_versions(
        session,
        graph_version=graph_version,
        chapter_order=chapter_order,
        facts=finish_fact_rows,
        visible_relation_ids=visible_relation_ids,
    )
    pulled_facts_by_case_id = _persist_pulled_results(
        session,
        annotation=annotation,
        graph_version=graph_version,
        pulled_results=pulled_results,
        authorized_text_chunk_ids=authorized_text_chunk_ids,
        entities_by_ref=entities_by_ref,
    )
    session.flush()
    return PersistedGraphResult(
        graph_version=graph_version,
        finish_facts_by_ref=finish_facts_by_ref,
        pulled_facts_by_case_id=pulled_facts_by_case_id,
    )
