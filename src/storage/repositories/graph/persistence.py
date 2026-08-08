"""
章节语义标注到版本事实图的原子写入
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.agents.annotation.schema import (
    RELATION_DEFINITIONS,
    BoundChapterAnnotation,
    BoundEntity,
    EntityType,
    EvidenceList,
    ResolvedCase,
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


@dataclass(slots=True)
class PersistedGraphResult:
    """2026-08-07 用于返回图版本和系统目标事实映射"""

    graph_version: GraphVersion
    dialogue_facts_by_candidate_key: dict[str, GraphFact]
    resolved_facts_by_case_id: dict[str, GraphFact]


@dataclass(slots=True)
class _RelationDraft:
    """2026-08-07 用于在单章内汇总同一稳定关系的多次变化"""

    relation: GraphRelation
    previous_revision: int
    relation_type: str
    attributes: dict[str, Any]
    is_active: bool
    changes: list[dict[str, Any]]


def _normalized_name(value: str) -> str:
    """2026-08-07 用于生成实体名称精确解析键"""
    return unicodedata.normalize("NFC", value).strip().casefold()


def stable_annotation_fact_id(
    annotation_id: str,
    chunk_id: int,
    domain: str,
    ordinal: int,
) -> str:
    """2026-08-07 用于按章节标注位置生成稳定事实 ID"""
    return str(uuid5(UUID(annotation_id), f"{chunk_id}:{domain}:{ordinal}"))


def _graph_version_id(run_id: str, chapter_id: int) -> str:
    """2026-08-07 用于为同一 run 章节生成事务重试稳定图版本 ID"""
    return str(uuid5(NAMESPACE_URL, f"noveliq:graph-version:{run_id}:{chapter_id}"))


def _relation_id(
    run_id: str,
    from_entity_id: int,
    to_entity_id: int,
    relation_type: str,
    directionality: str,
) -> str:
    """2026-08-07 用于根据系统解析端点和类型生成稳定关系 ID"""
    left_id, right_id = from_entity_id, to_entity_id
    if directionality == "bidirectional" and left_id > right_id:
        left_id, right_id = right_id, left_id
    return str(
        uuid5(
            NAMESPACE_URL,
            (
                f"noveliq:relation:{run_id}:{left_id}:{right_id}:"
                f"{relation_type}:{directionality}"
            ),
        )
    )


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


def _validate_annotation_chunks(
    session: Session,
    *,
    annotation: ChapterAnnotationRecord,
    payload: BoundChapterAnnotation,
) -> None:
    """2026-08-07 用于复核新合同 payload 只覆盖当前 run 真实章节 chunk"""
    expected = list(
        session.execute(
            select(Chunk.chunk_id)
            .where(
                Chunk.run_id == annotation.run_id,
                Chunk.chapter_id == annotation.chapter_id,
            )
            .order_by(Chunk.chunk_id)
        ).scalars()
    )
    actual = [chunk.chunk_id for chunk in payload.chunks]
    if actual != expected:
        raise ValueError(
            "章节 payload chunk 顺序与数据库不一致: "
            f"expected={expected} actual={actual}"
        )


def _entity_attributes(entity: BoundEntity, entity_type: EntityType) -> dict[str, Any]:
    """2026-08-07 用于提取系统绑定实体的持久化属性"""
    attributes: dict[str, Any] = {"entity_type": entity_type}
    if entity.description is not None:
        attributes["description"] = entity.description
    return attributes


def _resolve_entities(
    session: Session,
    *,
    annotation: ChapterAnnotationRecord,
    payload: BoundChapterAnnotation,
) -> dict[str, GraphEntity]:
    """2026-08-07 用于按规范化名称匹配或创建实体并维护出现边界"""
    appearances: dict[str, list[tuple[int, EntityType, BoundEntity]]] = {}
    display_names: dict[str, str] = {}
    for chunk in payload.chunks:
        for field_name, entity_type in _ENTITY_FIELDS:
            for item in getattr(chunk.entities, field_name):
                key = _normalized_name(item.name)
                existing_name = display_names.get(key)
                if existing_name is not None and existing_name != item.name:
                    raise ValueError(
                        f"实体名称规范化后冲突: {existing_name} / {item.name}"
                    )
                display_names[key] = item.name
                appearances.setdefault(key, []).append((chunk.chunk_id, entity_type, item))

    existing_by_key: dict[str, list[GraphEntity]] = {}
    for entity in session.execute(
        select(GraphEntity).where(GraphEntity.run_id == annotation.run_id)
    ).scalars():
        existing_by_key.setdefault(
            _normalized_name(entity.canonical_name),
            [],
        ).append(entity)

    resolved: dict[str, GraphEntity] = {}
    for key, items in appearances.items():
        entity_types = {entity_type for _chunk_id, entity_type, _item in items}
        if len(entity_types) != 1:
            raise ValueError(f"同一实体名称被声明为多个大类: {display_names[key]}")
        entity_type = next(iter(entity_types))
        chunk_ids = [chunk_id for chunk_id, _item_type, _item in items]
        attributes: dict[str, Any] = {}
        for _chunk_id, _item_type, item in items:
            attributes.update(_entity_attributes(item, entity_type))
        matches = existing_by_key.get(key, [])
        if len(matches) > 1:
            raise ValueError(f"实体名称匹配到多个节点: {display_names[key]}")
        if matches:
            entity = matches[0]
            if entity.entity_type != entity_type:
                raise ValueError(
                    f"实体名称已属于其他大类: {display_names[key]} "
                    f"expected={entity_type} actual={entity.entity_type}"
                )
            entity.first_seen_chunk = min(entity.first_seen_chunk, min(chunk_ids))
            entity.last_seen_chunk = max(entity.last_seen_chunk, max(chunk_ids))
            entity.attributes = {**dict(entity.attributes or {}), **attributes}
        else:
            entity = GraphEntity(
                run_id=annotation.run_id,
                canonical_name=display_names[key],
                entity_type=entity_type,
                attributes=attributes,
                first_seen_chunk=min(chunk_ids),
                last_seen_chunk=max(chunk_ids),
            )
            session.add(entity)
            session.flush()
            existing_by_key[key] = [entity]
        resolved[key] = entity
    return resolved


def _entity(
    entities_by_name: dict[str, GraphEntity],
    name: str | None,
) -> GraphEntity | None:
    """2026-08-07 用于按系统已校验名称读取图实体"""
    if name is None:
        return None
    entity = entities_by_name.get(_normalized_name(name))
    if entity is None:
        raise ValueError(f"事实端点实体未被系统解析: {name}")
    return entity


def _entity_descriptor(entity: GraphEntity | None) -> dict[str, Any] | None:
    """2026-08-07 用于把已解析实体转换为事实稳定描述"""
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
    chunk_id: int,
    domain: str,
    ordinal: int,
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
    """2026-08-07 用于从系统绑定位置构造单个不可变事实版本"""
    return GraphFact(
        graph_version_id=graph_version.graph_version_id,
        run_id=annotation.run_id,
        chapter_id=annotation.chapter_id,
        fact_id=stable_annotation_fact_id(
            annotation.annotation_id,
            chunk_id,
            domain,
            ordinal,
        ),
        fact_revision=1,
        fact_type=domain,
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
        source_kind="annotation",
        annotation_id=annotation.annotation_id,
        payload_path=f"chunks/{chunk_id}/{domain}/{ordinal}",
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


def _persist_annotation_facts(
    session: Session,
    *,
    annotation: ChapterAnnotationRecord,
    payload: BoundChapterAnnotation,
    graph_version: GraphVersion,
    chapter_order: int,
    entities_by_name: dict[str, GraphEntity],
) -> tuple[list[GraphFact], dict[str, GraphFact]]:
    """2026-08-07 用于按 chunk 和领域顺序写入全部正式语义事实"""
    facts: list[GraphFact] = []
    dialogue_by_candidate: dict[str, GraphFact] = {}
    active_relations = _active_relation_keys(
        session,
        run_id=annotation.run_id,
        chapter_order=chapter_order,
    )

    for chunk in payload.chunks:
        chunk_id = chunk.chunk_id
        for ordinal, observation in enumerate(chunk.character_observations):
            subject = _entity(entities_by_name, observation.character)
            content = {
                "kind": "character_observation",
                "chunk_id": chunk_id,
                "entity": _entity_descriptor(subject),
                "role_function": observation.role_function,
                "action": observation.action,
                "action_type": observation.action_type,
                "emotion": observation.emotion,
                "reason": observation.reason,
            }
            fact = _new_graph_fact(
                graph_version=graph_version,
                annotation=annotation,
                chunk_id=chunk_id,
                domain="character_observation",
                ordinal=ordinal,
                subject=subject,
                predicate=str(observation.action_type),
                object_value=None,
                value={
                    "role_function": observation.role_function,
                    "action": observation.action,
                    "emotion": observation.emotion,
                },
                participants=[],
                story_time=None,
                assertion="affirmed",
                confidence=str(observation.confidence),
                content=content,
                evidence=observation.evidence,
            )
            session.add(fact)
            facts.append(fact)

        for ordinal, dialogue in enumerate(chunk.dialogues):
            speaker = _entity(entities_by_name, dialogue.speaker)
            speaker_descriptor = _entity_descriptor(speaker)
            content = {
                "kind": "dialogue",
                "chunk_id": chunk_id,
                "candidate_key": dialogue.candidate_key,
                "content": dialogue.content,
                "start": dialogue.start,
                "end": dialogue.end,
                "description": dialogue.description,
                "speaker": speaker_descriptor,
                "tone": dialogue.tone,
                "is_inner_monologue": dialogue.is_inner_monologue,
                "reason": dialogue.reason,
            }
            fact = _new_graph_fact(
                graph_version=graph_version,
                annotation=annotation,
                chunk_id=chunk_id,
                domain="dialogue",
                ordinal=ordinal,
                subject=speaker,
                predicate="spoke",
                object_value=None,
                value={
                    "content": dialogue.content,
                    "start": dialogue.start,
                    "end": dialogue.end,
                    "description": dialogue.description,
                    "tone": dialogue.tone,
                    "is_inner_monologue": dialogue.is_inner_monologue,
                },
                participants=(
                    [{"role": "speaker", "entity": speaker_descriptor}]
                    if speaker_descriptor is not None
                    else []
                ),
                story_time=None,
                assertion="affirmed",
                confidence=str(dialogue.confidence),
                content=content,
                evidence=dialogue.evidence,
            )
            session.add(fact)
            facts.append(fact)
            dialogue_by_candidate[dialogue.candidate_key] = fact

        for ordinal, event_item in enumerate(chunk.events):
            participants: list[dict[str, Any]] = []
            participant_entities: list[GraphEntity] = []
            for participant in event_item.participants:
                entity = _entity(entities_by_name, participant.entity)
                if entity is None:
                    raise ValueError("event participant 缺少实体")
                participant_entities.append(entity)
                participants.append(
                    {
                        "role": participant.participation,
                        "entity": _entity_descriptor(entity),
                    }
                )
            location = _entity(entities_by_name, event_item.location)
            content = {
                "kind": "event",
                "chunk_id": chunk_id,
                "description": event_item.description,
                "participants": participants,
                "location": _entity_descriptor(location),
                "reason": event_item.reason,
            }
            fact = _new_graph_fact(
                graph_version=graph_version,
                annotation=annotation,
                chunk_id=chunk_id,
                domain="event",
                ordinal=ordinal,
                subject=participant_entities[0] if participant_entities else None,
                predicate="event",
                object_value=_entity_descriptor(location),
                value={"description": event_item.description},
                participants=participants,
                story_time=(
                    event_item.story_time.model_dump(mode="json")
                    if event_item.story_time is not None
                    else None
                ),
                assertion="affirmed",
                confidence=str(event_item.confidence),
                content=content,
                evidence=event_item.evidence,
            )
            session.add(fact)
            facts.append(fact)

        for ordinal, relation_item in enumerate(chunk.relations):
            from_entity = _entity(entities_by_name, relation_item.from_entity)
            to_entity = _entity(entities_by_name, relation_item.to_entity)
            if from_entity is None or to_entity is None:
                raise ValueError("relation 端点缺少实体")
            relation_type = str(relation_item.relation_type)
            definition = RELATION_DEFINITIONS[relation_type]
            directionality = str(relation_item.directionality)
            semantics = str(relation_item.relation_semantics)
            key = _relation_key(
                int(from_entity.entity_id),
                int(to_entity.entity_id),
                directionality=directionality,
                relation_semantics=semantics,
                relation_type=relation_type,
            )
            relation_id = active_relations.get(key)
            if relation_id is None:
                if str(relation_item.change_kind) != "assert":
                    raise ValueError(
                        "关系变化未匹配到已有活动关系: "
                        f"{relation_item.from_entity} {relation_type} {relation_item.to_entity}"
                    )
                relation_id = _relation_id(
                    annotation.run_id,
                    int(from_entity.entity_id),
                    int(to_entity.entity_id),
                    relation_type,
                    directionality,
                )
                active_relations[key] = relation_id
            representative_id = (
                min(int(from_entity.entity_id), int(to_entity.entity_id))
                if definition["semantics"] == "same_character"
                else None
            )
            content = {
                "kind": "relation",
                "chunk_id": chunk_id,
                "from_entity": _entity_descriptor(from_entity),
                "to_entity": _entity_descriptor(to_entity),
                "relation_type": relation_type,
                "change_kind": relation_item.change_kind,
                "relation_id": relation_id,
                "directionality": directionality,
                "relation_semantics": semantics,
                "representative_entity_id": representative_id,
                "reason": relation_item.reason,
            }
            fact = _new_graph_fact(
                graph_version=graph_version,
                annotation=annotation,
                chunk_id=chunk_id,
                domain="relation",
                ordinal=ordinal,
                subject=from_entity,
                predicate=relation_type,
                object_value=_entity_descriptor(to_entity),
                value=None,
                participants=[
                    {"role": "from", "entity": _entity_descriptor(from_entity)},
                    {"role": "to", "entity": _entity_descriptor(to_entity)},
                ],
                story_time=None,
                assertion="affirmed",
                confidence=str(relation_item.confidence),
                content=content,
                evidence=relation_item.evidence,
            )
            session.add(fact)
            facts.append(fact)

        for ordinal, state_item in enumerate(chunk.states):
            subject = _entity(entities_by_name, state_item.entity)
            object_entity = _entity(entities_by_name, state_item.object)
            content = {
                "kind": "state",
                "chunk_id": chunk_id,
                "entity": _entity_descriptor(subject),
                "predicate": state_item.predicate,
                "object": _entity_descriptor(object_entity),
                "value": state_item.value,
                "assertion": state_item.assertion,
                "reason": state_item.reason,
            }
            fact = _new_graph_fact(
                graph_version=graph_version,
                annotation=annotation,
                chunk_id=chunk_id,
                domain="state",
                ordinal=ordinal,
                subject=subject,
                predicate=state_item.predicate,
                object_value=_entity_descriptor(object_entity),
                value=state_item.value,
                participants=[],
                story_time=(
                    state_item.story_time.model_dump(mode="json")
                    if state_item.story_time is not None
                    else None
                ),
                assertion=str(state_item.assertion),
                confidence=str(state_item.confidence),
                content=content,
                evidence=state_item.evidence,
            )
            session.add(fact)
            facts.append(fact)

        for ordinal, foreshadowing in enumerate(chunk.foreshadowings):
            content = {
                "kind": "foreshadowing",
                "chunk_id": chunk_id,
                **foreshadowing.model_dump(
                    mode="json",
                    exclude={"evidence", "confidence"},
                ),
            }
            fact = _new_graph_fact(
                graph_version=graph_version,
                annotation=annotation,
                chunk_id=chunk_id,
                domain="foreshadowing",
                ordinal=ordinal,
                subject=None,
                predicate=str(foreshadowing.setup_kind),
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
                confidence=str(foreshadowing.confidence),
                content=content,
                evidence=foreshadowing.evidence,
            )
            session.add(fact)
            facts.append(fact)

    session.flush()
    return facts, dialogue_by_candidate


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


def _apply_relation_change(
    *,
    draft: _RelationDraft,
    fact: GraphFact,
    change_kind: str,
    relation_type: str,
) -> None:
    """2026-08-07 用于在关系草稿上应用闭合生命周期变化"""
    before = {
        "relation_type": draft.relation_type,
        "attributes": dict(draft.attributes),
        "is_active": draft.is_active,
    }
    if change_kind == "assert":
        draft.relation_type = relation_type
        draft.is_active = True
        draft.attributes["support_count"] = int(
            draft.attributes.get("support_count", 0)
        ) + 1
    elif change_kind == "reinforce":
        draft.is_active = True
        draft.attributes["support_count"] = int(
            draft.attributes.get("support_count", 1)
        ) + 1
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


def _persist_relation_versions(
    session: Session,
    *,
    graph_version: GraphVersion,
    chapter_order: int,
    facts: list[GraphFact],
) -> None:
    """2026-08-07 用于按系统解析 relation_id 汇总本章关系版本"""
    drafts: dict[str, _RelationDraft] = {}
    for fact in facts:
        content = dict(fact.content)
        if content.get("kind") != "relation":
            continue
        if fact.subject_entity_id is None or not isinstance(fact.object, dict):
            raise ValueError(f"relation 事实缺少已解析端点: {fact.fact_id}")
        relation_id = str(content["relation_id"])
        draft = drafts.get(relation_id)
        if draft is None:
            existing = session.get(GraphRelation, relation_id)
            if existing is None:
                existing = GraphRelation(
                    relation_id=relation_id,
                    run_id=graph_version.run_id,
                    from_entity_id=int(fact.subject_entity_id),
                    to_entity_id=int(fact.object["entity_id"]),
                    directionality=str(content["directionality"]),
                    relation_semantics=str(content["relation_semantics"]),
                )
                session.add(existing)
                session.flush()
                attributes: dict[str, Any] = {}
                representative = content.get("representative_entity_id")
                if representative is not None:
                    attributes["representative_entity_id"] = int(representative)
                draft = _RelationDraft(
                    relation=existing,
                    previous_revision=0,
                    relation_type=str(content["relation_type"]),
                    attributes=attributes,
                    is_active=False,
                    changes=[],
                )
            else:
                draft = _previous_relation_draft(
                    session,
                    run_id=graph_version.run_id,
                    relation_id=relation_id,
                    chapter_order=chapter_order,
                )
            drafts[relation_id] = draft
        _apply_relation_change(
            draft=draft,
            fact=fact,
            change_kind=str(content["change_kind"]),
            relation_type=str(content["relation_type"]),
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
    resolved_case: ResolvedCase,
    entities_by_name: dict[str, GraphEntity],
) -> GraphEntity:
    """2026-08-07 用于把案例语义说话人解析为人物图节点"""
    key = _normalized_name(resolved_case.speaker)
    current = entities_by_name.get(key)
    if current is not None:
        if current.entity_type != "character":
            raise ValueError("resolve_case speaker 必须解析为人物实体")
        return current
    matches = [
        entity
        for entity in session.execute(
            select(GraphEntity).where(GraphEntity.run_id == run_id)
        ).scalars()
        if _normalized_name(entity.canonical_name) == key
    ]
    if len(matches) > 1:
        raise ValueError(f"resolve_case speaker 匹配到多个实体: {resolved_case.speaker}")
    if matches:
        entity = matches[0]
        if entity.entity_type != "character":
            raise ValueError("resolve_case speaker 名称已属于非人物实体")
        entity.last_seen_chunk = max(
            entity.last_seen_chunk,
            resolved_case.evidence_chunk_id,
        )
        return entity
    entity = GraphEntity(
        run_id=run_id,
        canonical_name=resolved_case.speaker,
        entity_type="character",
        attributes={},
        first_seen_chunk=resolved_case.evidence_chunk_id,
        last_seen_chunk=resolved_case.evidence_chunk_id,
    )
    session.add(entity)
    session.flush()
    return entity


def _next_fact_revision(session: Session, run_id: str, fact_id: str) -> int:
    """2026-08-07 用于读取同一事实下一条不可变修订号"""
    revision = session.execute(
        select(func.max(GraphFact.fact_revision)).where(
            GraphFact.run_id == run_id,
            GraphFact.fact_id == fact_id,
        )
    ).scalar_one()
    return int(revision or 0) + 1


def _validate_case_target(target: GraphFact, resolved_case: ResolvedCase) -> None:
    """2026-08-07 用于核对案例内部目标仍指向同一未确认对话"""
    content = dict(target.content)
    if target.fact_type != "dialogue" or content.get("kind") != "dialogue":
        raise ValueError(f"案例目标不是对话事实: {resolved_case.case_id}")
    expected = {
        "candidate_key": content.get("candidate_key"),
        "chunk_id": target.effective_chunk_id,
        "start": content.get("start"),
        "end": content.get("end"),
        "text": content.get("content"),
    }
    for field_name, expected_value in expected.items():
        if resolved_case.target_ref.get(field_name) != expected_value:
            raise ValueError(
                f"案例目标字段与历史对话不一致: "
                f"case_id={resolved_case.case_id} field={field_name}"
            )
    if content.get("speaker") is not None:
        raise ValueError(f"案例目标对话已经具有说话人: {resolved_case.case_id}")


def _persist_resolved_cases(
    session: Session,
    *,
    annotation: ChapterAnnotationRecord,
    graph_version: GraphVersion,
    resolved_cases: list[ResolvedCase],
    authorized_text_chunk_ids: set[int],
    entities_by_name: dict[str, GraphEntity],
) -> dict[str, GraphFact]:
    """2026-08-07 用于把案例解决写成历史对话事实新修订"""
    rows_by_case_id: dict[str, GraphFact] = {}
    for resolved_case in resolved_cases:
        if resolved_case.evidence_chunk_id not in authorized_text_chunk_ids:
            raise ValueError(
                "resolve_case 使用了未经系统读取授权的原文: "
                f"{resolved_case.evidence_chunk_id}"
            )
        target_fact_id = str(resolved_case.target_ref.get("fact_id") or "")
        target_fact_revision = resolved_case.target_ref.get("fact_revision")
        if not target_fact_id or not isinstance(target_fact_revision, int):
            raise ValueError(f"案例缺少历史事实目标: {resolved_case.case_id}")
        target = session.execute(
            select(GraphFact).where(
                GraphFact.run_id == annotation.run_id,
                GraphFact.fact_id == target_fact_id,
                GraphFact.fact_revision == target_fact_revision,
                GraphFact.source_kind == "annotation",
            )
        ).scalar_one_or_none()
        if target is None:
            raise ValueError(f"案例目标事实不存在或跨 run: {resolved_case.case_id}")
        _validate_case_target(target, resolved_case)
        speaker = _resolution_speaker_entity(
            session,
            run_id=annotation.run_id,
            resolved_case=resolved_case,
            entities_by_name=entities_by_name,
        )
        speaker_descriptor = _entity_descriptor(speaker)
        content = dict(target.content)
        content["speaker"] = speaker_descriptor
        content["resolved_by_case_id"] = resolved_case.case_id
        evidence = EvidenceList.model_validate(
            [
                *list(target.evidence),
                TextEvidence(
                    reason=resolved_case.reason,
                    chunk_id=resolved_case.evidence_chunk_id,
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
            payload_path=f"case_resolution/{resolved_case.case_id}",
        )
        session.add(row)
        session.flush()
        rows_by_case_id[resolved_case.case_id] = row
    return rows_by_case_id


def persist_completion_graph(
    session: Session,
    *,
    annotation: ChapterAnnotationRecord,
    resolved_cases: list[ResolvedCase],
    authorized_text_chunk_ids: set[int],
) -> PersistedGraphResult:
    """2026-08-07 用于在一个图版本中写入正式标注和连续性修订"""
    payload = BoundChapterAnnotation.model_validate(annotation.payload)
    _validate_annotation_chunks(
        session,
        annotation=annotation,
        payload=payload,
    )
    chapter_order, first_chunk_id, last_chunk_id = _chapter_bounds(
        session,
        annotation.run_id,
        annotation.chapter_id,
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

    entities_by_name = _resolve_entities(
        session,
        annotation=annotation,
        payload=payload,
    )
    facts, dialogue_by_candidate = _persist_annotation_facts(
        session,
        annotation=annotation,
        payload=payload,
        graph_version=graph_version,
        chapter_order=chapter_order,
        entities_by_name=entities_by_name,
    )
    _persist_state_versions(
        session,
        graph_version=graph_version,
        chapter_order=chapter_order,
        facts=facts,
    )
    _persist_relation_versions(
        session,
        graph_version=graph_version,
        chapter_order=chapter_order,
        facts=facts,
    )
    resolved_facts = _persist_resolved_cases(
        session,
        annotation=annotation,
        graph_version=graph_version,
        resolved_cases=resolved_cases,
        authorized_text_chunk_ids=authorized_text_chunk_ids,
        entities_by_name=entities_by_name,
    )
    session.flush()
    return PersistedGraphResult(
        graph_version=graph_version,
        dialogue_facts_by_candidate_key=dialogue_by_candidate,
        resolved_facts_by_case_id=resolved_facts,
    )
