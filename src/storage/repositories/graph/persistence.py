"""
章节语义标注到版本事实图的原子写入
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.agents.annotation.schema import (
    RELATION_DEFINITIONS,
    BoundChapterAnnotation,
    BoundEntity,
    EntityType,
    ResolvedCase,
)
from src.storage.models import (
    ChapterAnnotationRecord,
    Chunk,
    DialogueRecord,
    EntityStateVersion,
    ForeshadowingThread,
    GraphEntity,
    GraphFact,
    GraphRelation,
    GraphRelationVersion,
    GraphVersion,
)


@dataclass(slots=True)
class PersistedGraphResult:
    """2026-08-11 用于返回图版本和案例解决目标映射（对话/线程/关系事实）"""

    graph_version: GraphVersion
    resolved_targets_by_case_id: dict[str, Any]


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
    """2026-08-11 用于提取系统绑定实体的持久化属性（null 键保留以表达 JSON Merge Patch 删除）"""
    attributes: dict[str, Any] = {"entity_type": entity_type}
    if entity.description is not None:
        attributes["description"] = entity.description
    for key, value in (entity.attributes or {}).items():
        attributes[key] = value
    return attributes


def _resolve_entities(
    session: Session,
    *,
    annotation: ChapterAnnotationRecord,
    payload: BoundChapterAnnotation,
) -> tuple[dict[str, GraphEntity], dict[int, list[dict[str, Any]]]]:
    """2026-08-11 用于按规范化名称匹配或创建实体并维护出现边界，返回实体表与属性变化"""
    appearances: dict[str, list[tuple[int, EntityType, BoundEntity]]] = {}
    display_names: dict[str, str] = {}
    for chunk in payload.chunks:
        for item in chunk.entities.entities:
            key = _normalized_name(item.name)
            existing_name = display_names.get(key)
            if existing_name is not None and existing_name != item.name:
                raise ValueError(
                    f"实体名称规范化后冲突: {existing_name} / {item.name}"
                )
            display_names[key] = item.name
            appearances.setdefault(key, []).append(
                (chunk.chunk_id, item.entity_type, item)
            )

    existing_by_key: dict[str, list[GraphEntity]] = {}
    for entity in session.execute(
        select(GraphEntity).where(GraphEntity.run_id == annotation.run_id)
    ).scalars():
        existing_by_key.setdefault(
            _normalized_name(entity.canonical_name),
            [],
        ).append(entity)

    resolved: dict[str, GraphEntity] = {}
    attribute_patches: dict[int, list[dict[str, Any]]] = {}
    for key, items in appearances.items():
        entity_types = {entity_type for _chunk_id, entity_type, _item in items}
        if len(entity_types) != 1:
            raise ValueError(f"同一实体名称被声明为多个大类: {display_names[key]}")
        entity_type: EntityType = next(iter(entity_types))
        chunk_ids = [chunk_id for chunk_id, _item_type, _item in items]
        attributes: dict[str, Any] = {}
        tags: list[str] = []
        for _chunk_id, _item_type, item in items:
            attributes.update(_entity_attributes(item, entity_type))
            for tag in item.tags:
                if tag not in tags:
                    tags.append(tag)
        matches = existing_by_key.get(key, [])
        if len(matches) > 1:
            raise ValueError(f"实体名称匹配到多个节点: {display_names[key]}")
        if matches:
            entity = matches[0]
            if entity.entity_type != entity_type:
                # 2026-08-08 同一名称跨章变更大类不是归类波动而是身份复用：
                # 前文“剑”是 item 器物，后文出现有灵的“剑灵”应使用不同名称提交，
                # 这里直接报错，避免静默吞掉后文的新身份
                raise ValueError(
                    f"实体名称已属于其他大类: {display_names[key]} "
                    f"expected={entity.entity_type} actual={entity_type}；"
                    "若后文是寄宿或附身等独立身份，请改用区分性名称重新提交"
                )
            entity.first_seen_chunk = min(entity.first_seen_chunk, min(chunk_ids))
            entity.last_seen_chunk = max(entity.last_seen_chunk, max(chunk_ids))
            # 2026-08-11 属性 JSON Merge Patch：本次提交字段替换旧值，null 删除，未提交字段沿用
            before = dict(entity.attributes or {})
            merged = dict(entity.attributes or {})
            for field_name, value in attributes.items():
                if value is None:
                    merged.pop(field_name, None)
                else:
                    merged[field_name] = value
            entity.attributes = merged
            if tags:
                entity.tags = list(dict.fromkeys(tags))
            after = dict(entity.attributes or {})
            field_changes: list[dict[str, Any]] = []
            for field_name in before.keys() | after.keys():
                if before.get(field_name) != after.get(field_name):
                    field_changes.append(
                        {
                            "field": field_name,
                            "before": before.get(field_name),
                            "after": after.get(field_name),
                            "chunk_id": min(chunk_ids),
                        }
                    )
            if field_changes:
                attribute_patches[int(entity.entity_id)] = field_changes
        else:
            entity = GraphEntity(
                run_id=annotation.run_id,
                canonical_name=display_names[key],
                entity_type=entity_type,
                tags=tags,
                attributes=attributes,
                first_seen_chunk=min(chunk_ids),
                last_seen_chunk=max(chunk_ids),
            )
            session.add(entity)
            session.flush()
            existing_by_key[key] = [entity]
        resolved[key] = entity
    for key, entities in existing_by_key.items():
        if key not in resolved and len(entities) == 1:
            resolved[key] = entities[0]
    return resolved, attribute_patches


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
) -> GraphFact:
    """2026-08-11 用于从系统绑定位置构造单个不可变事实版本"""
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


def _bump_referenced_last_seen(
    entities_by_name: dict[str, GraphEntity],
    chunk: Any,
    chunk_id: int,
) -> None:
    """2026-08-11 用于任意工具引用实体时自动更新 last_seen_chunk（含对话/观察/事件/关系端点）"""
    referenced: dict[str, None] = {}
    for entity in chunk.entities.entities:
        referenced.setdefault(_normalized_name(entity.name), None)
    for observation in chunk.character_observations:
        referenced.setdefault(_normalized_name(observation.character), None)
    for dialogue in chunk.dialogues:
        if dialogue.speaker is not None:
            referenced.setdefault(_normalized_name(dialogue.speaker), None)
    for event_item in chunk.events:
        for participant in event_item.participants:
            referenced.setdefault(_normalized_name(participant.entity), None)
    for relation_item in chunk.relations:
        referenced.setdefault(_normalized_name(relation_item.from_entity), None)
        referenced.setdefault(_normalized_name(relation_item.to_entity), None)
    for key in referenced:
        entity = entities_by_name.get(key)
        if entity is not None:
            entity.last_seen_chunk = max(int(entity.last_seen_chunk), chunk_id)


def _persist_annotation_facts(
    session: Session,
    *,
    annotation: ChapterAnnotationRecord,
    payload: BoundChapterAnnotation,
    graph_version: GraphVersion,
    chapter_order: int,
    entities_by_name: dict[str, GraphEntity],
    attribute_patches: dict[int, list[dict[str, Any]]],
) -> tuple[list[GraphFact], dict[int, list[dict[str, Any]]]]:
    """2026-08-11 用于按 chunk 和领域顺序写入正式语义事实（对话单独落 dialogue_records）"""
    facts: list[GraphFact] = []
    active_relations = _active_relation_keys(
        session,
        run_id=annotation.run_id,
        chapter_order=chapter_order,
    )
    entity_by_id = {int(entity.entity_id): entity for entity in entities_by_name.values()}
    attribute_changes_by_entity: dict[int, list[dict[str, Any]]] = {}
    attribute_ordinal = 0

    for chunk in payload.chunks:
        chunk_id = chunk.chunk_id
        _bump_referenced_last_seen(
            entities_by_name,
            chunk,
            chunk_id,
        )
        for ordinal, observation in enumerate(chunk.character_observations):
            subject = _entity(entities_by_name, observation.character)
            content = {
                "kind": "character_observation",
                "chunk_id": chunk_id,
                "entity": _entity_descriptor(subject),
                "role_function": observation.role_function,
                "action": observation.action,
                "emotion": observation.emotion,
            }
            fact = _new_graph_fact(
                graph_version=graph_version,
                annotation=annotation,
                chunk_id=chunk_id,
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
                story_time=None,
                assertion="affirmed",
                confidence="medium",
                content=content,
            )
            session.add(fact)
            facts.append(fact)

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
                        "role": str(participant.role),
                        "entity": _entity_descriptor(entity),
                    }
                )
            content = {
                "kind": "event",
                "chunk_id": chunk_id,
                "description": event_item.description,
                "participants": participants,
            }
            fact = _new_graph_fact(
                graph_version=graph_version,
                annotation=annotation,
                chunk_id=chunk_id,
                domain="event",
                ordinal=ordinal,
                subject=participant_entities[0] if participant_entities else None,
                predicate="event",
                object_value=None,
                value={"description": event_item.description},
                participants=participants,
                story_time=None,
                assertion="affirmed",
                confidence="medium",
                content=content,
            )
            session.add(fact)
            facts.append(fact)

        for ordinal, relation_item in enumerate(chunk.relations):
            from_entity = _entity(entities_by_name, relation_item.from_entity)
            to_entity = _entity(entities_by_name, relation_item.to_entity)
            if from_entity is None or to_entity is None:
                raise ValueError("relation 端点缺少实体")
            relation_type = str(relation_item.relation_type)
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
                relation_id = _relation_id(
                    annotation.run_id,
                    int(from_entity.entity_id),
                    int(to_entity.entity_id),
                    relation_type,
                    directionality,
                )
                active_relations[key] = relation_id
                change_kind = "assert"
            else:
                # 已存在的同一条边：接受为 no-op，只更新 last_seen 与证据事实，
                # 不产生关系版本；真正强化/削弱/解除走 resolve_fact_case
                change_kind = "noop"
            content = {
                "kind": "relation",
                "chunk_id": chunk_id,
                "from_entity": _entity_descriptor(from_entity),
                "to_entity": _entity_descriptor(to_entity),
                "relation_type": relation_type,
                "change_kind": change_kind,
                "relation_id": relation_id,
                "directionality": directionality,
                "relation_semantics": semantics,
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
                confidence="medium",
                content=content,
            )
            session.add(fact)
            facts.append(fact)

        for ordinal, foreshadowing in enumerate(chunk.foreshadowings):
            content = {
                "kind": "foreshadowing",
                "chunk_id": chunk_id,
                "description": foreshadowing.description,
                "confidence": str(foreshadowing.confidence),
            }
            fact = _new_graph_fact(
                graph_version=graph_version,
                annotation=annotation,
                chunk_id=chunk_id,
                domain="foreshadowing",
                ordinal=ordinal,
                subject=None,
                predicate="其他",
                object_value=None,
                value={
                    "description": foreshadowing.description,
                    "setup_summary": foreshadowing.description,
                },
                participants=[],
                story_time=None,
                assertion="affirmed",
                confidence=str(foreshadowing.confidence),
                content=content,
            )
            session.add(fact)
            facts.append(fact)

    # 属性变化事实与 chunk 循环无关（chunk_id 取自 patch 自身），
    # 统一在 chunk 循环后生成，避免多 chunk 章节对同一 patch 重复写入
    for entity_id, patches in attribute_patches.items():
        entity = entity_by_id.get(entity_id)
        if entity is None:
            raise ValueError(f"属性变化事实缺少已解析实体: {entity_id}")
        for patch in patches:
            attribute_ordinal += 1
            fact = _new_graph_fact(
                graph_version=graph_version,
                annotation=annotation,
                chunk_id=int(patch["chunk_id"]),
                domain="entity_attribute",
                ordinal=attribute_ordinal,
                subject=entity,
                predicate=str(patch["field"]),
                object_value=None,
                value=patch["after"],
                participants=[],
                story_time=None,
                assertion="affirmed",
                confidence="medium",
                content={
                    "kind": "entity_attribute",
                    "field": patch["field"],
                    "before": patch["before"],
                    "after": patch["after"],
                    "chunk_id": patch["chunk_id"],
                },
            )
            session.add(fact)
            facts.append(fact)
            attribute_changes_by_entity.setdefault(entity_id, []).append(
                {
                    "field": patch["field"],
                    "before": patch["before"],
                    "after": patch["after"],
                    "fact_id": fact.fact_id,
                    "fact_revision": fact.fact_revision,
                    "chunk_id": patch["chunk_id"],
                }
            )

    session.flush()
    return facts, attribute_changes_by_entity


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
    """2026-08-11 用于把观察事实转换为实体状态字段更新"""
    content = dict(fact.content)
    kind = content.get("kind")
    if kind == "character_observation":
        return {
            "role_function": content["role_function"],
            "action": content["action"],
            "emotion": content["emotion"],
        }
    return {}


def _persist_state_versions(
    session: Session,
    *,
    graph_version: GraphVersion,
    chapter_order: int,
    facts: list[GraphFact],
    entities_by_name: dict[str, GraphEntity],
    attribute_changes: dict[int, list[dict[str, Any]]],
) -> None:
    """2026-08-11 用于汇总同一实体本章观察与属性变化，一章每实体产生一个版本"""
    entity_by_id = {int(entity.entity_id): entity for entity in entities_by_name.values()}
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
            entity = entity_by_id.get(entity_id)
            if entity is None:
                raise ValueError(f"实体状态版本缺少已解析实体: {entity_id}")
            state_by_entity[entity_id] = {
                **dict(entity.attributes or {}),
                **previous_state,
            }
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

    for entity_id, changes in attribute_changes.items():
        if entity_id not in state_by_entity:
            previous_revision, previous_state = _previous_entity_state(
                session,
                run_id=graph_version.run_id,
                entity_id=entity_id,
                chapter_order=chapter_order,
            )
            revision_by_entity[entity_id] = previous_revision
            entity = entity_by_id.get(entity_id)
            if entity is None:
                raise ValueError(f"实体状态版本缺少已解析实体: {entity_id}")
            state_by_entity[entity_id] = {
                **dict(entity.attributes or {}),
                **previous_state,
            }
            changes_by_entity[entity_id] = []
        for change in changes:
            if change["before"] == change["after"]:
                continue
            state = state_by_entity[entity_id]
            if change["after"] is None:
                state.pop(change["field"], None)
            else:
                state[change["field"]] = change["after"]
            changes_by_entity[entity_id].append(
                {
                    "field": change["field"],
                    "before": change["before"],
                    "after": change["after"],
                    "fact_id": change["fact_id"],
                    "fact_revision": change["fact_revision"],
                    "chunk_id": change["chunk_id"],
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
        change_kind = str(content["change_kind"])
        if change_kind == "noop":
            # 已存在同一条边的重复提交：接受为 no-op，不产生关系版本
            continue
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
                draft = _RelationDraft(
                    relation=existing,
                    previous_revision=0,
                    relation_type=str(content["relation_type"]),
                    attributes={},
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
            change_kind=change_kind,
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


def _target_chunk_id(resolved_case: ResolvedCase) -> int:
    """2026-08-11 用于读取案例登记时的原文 chunk 位置"""
    chunk_id = resolved_case.target_ref.get("chunk_id")
    if chunk_id is None:
        raise ValueError(f"案例目标缺少 chunk_id: {resolved_case.case_id}")
    return int(chunk_id)


def _resolve_case_entity(
    session: Session,
    *,
    run_id: str,
    name: str,
    entities_by_name: dict[str, GraphEntity],
    allowed_types: tuple[str, ...],
    chunk_id: int,
) -> GraphEntity:
    """2026-08-11 用于把案例端点名称解析为图实体节点"""
    key = _normalized_name(name)
    current = entities_by_name.get(key)
    if current is not None:
        if current.entity_type not in allowed_types:
            raise ValueError(
                f"案例端点实体类型不属于 {list(allowed_types)}: "
                f"{name}（实际 {current.entity_type}）"
            )
        return current
    matches = [
        entity
        for entity in session.execute(
            select(GraphEntity).where(GraphEntity.run_id == run_id)
        ).scalars()
        if _normalized_name(entity.canonical_name) == key
    ]
    if len(matches) > 1:
        raise ValueError(f"案例端点匹配到多个实体: {name}")
    if matches:
        entity = matches[0]
        if entity.entity_type not in allowed_types:
            raise ValueError(
                f"案例端点名称已属于其他大类: {name} "
                f"expected={list(allowed_types)} actual={entity.entity_type}"
            )
        entity.last_seen_chunk = max(
            entity.last_seen_chunk,
            chunk_id,
        )
        return entity
    if len(allowed_types) != 1:
        raise ValueError(
            f"案例端点实体未登记且大类不唯一，请先登记再解决: {name}"
        )
    entity = GraphEntity(
        run_id=run_id,
        canonical_name=name,
        entity_type=allowed_types[0],
        attributes={},
        first_seen_chunk=chunk_id,
        last_seen_chunk=chunk_id,
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


def _validate_dialogue_target(record: DialogueRecord, resolved_case: ResolvedCase) -> None:
    """2026-08-11 用于核对案例内部目标仍指向同一对话记录"""
    expected = {
        "chunk_id": int(record.chunk_id),
        "start": int(record.start),
        "end": int(record.end),
        "content": str(record.content),
    }
    for field_name, expected_value in expected.items():
        actual = resolved_case.target_ref.get(field_name)
        if actual is not None and actual != expected_value:
            raise ValueError(
                f"案例目标与对话记录不一致: "
                f"case_id={resolved_case.case_id} field={field_name}"
            )


def _persist_dialogue_resolution(
    session: Session,
    *,
    run_id: str,
    resolved_case: ResolvedCase,
) -> DialogueRecord:
    """2026-08-11 用于把 dialogue 动作解决结果直接更新对话记录表"""
    candidate_key = resolved_case.target_ref.get("dialogue_id")
    if not candidate_key:
        raise ValueError(f"dialogue 动作案例缺少对话目标: {resolved_case.case_id}")
    record = session.execute(
        select(DialogueRecord).where(
            DialogueRecord.run_id == run_id,
            DialogueRecord.candidate_key == str(candidate_key),
        )
    ).scalar_one_or_none()
    if record is None:
        raise ValueError(f"案例目标对话记录不存在或跨 run: {resolved_case.case_id}")
    _validate_dialogue_target(record, resolved_case)
    if resolved_case.speaker is not None:
        record.speaker = resolved_case.speaker
    if resolved_case.tone is not None:
        record.tone = resolved_case.tone
    if resolved_case.is_inner_monologue is not None:
        record.is_inner_monologue = resolved_case.is_inner_monologue
    record.updated_at = datetime.now(UTC)
    session.flush()
    return record


def _latest_relation_draft(
    session: Session,
    *,
    run_id: str,
    relation: GraphRelation,
    relation_type: str,
    attributes: dict[str, Any],
) -> tuple[_RelationDraft, GraphRelationVersion | None]:
    """2026-08-11 用于读取稳定关系最近版本状态构造变化草稿，并返回最新版本行"""
    latest = session.execute(
        select(GraphRelationVersion)
        .where(
            GraphRelationVersion.run_id == run_id,
            GraphRelationVersion.relation_id == relation.relation_id,
        )
        .order_by(GraphRelationVersion.relation_revision.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest is None:
        return (
            _RelationDraft(
                relation=relation,
                previous_revision=0,
                relation_type=relation_type,
                attributes=dict(attributes),
                is_active=False,
                changes=[],
            ),
            None,
        )
    return (
        _RelationDraft(
            relation=relation,
            previous_revision=int(latest.relation_revision),
            relation_type=str(latest.relation_type),
            attributes=dict(latest.attributes),
            is_active=bool(latest.is_active),
            changes=[],
        ),
        latest,
    )


def _persist_fact_resolution(
    session: Session,
    *,
    annotation: ChapterAnnotationRecord,
    graph_version: GraphVersion,
    resolved_case: ResolvedCase,
    entities_by_name: dict[str, GraphEntity],
) -> GraphFact:
    """2026-08-11 用于把 fact 动作案例写成关系事实版本（change_kind 表达建改删）"""
    relation_type = str(resolved_case.relation_type)
    definition = RELATION_DEFINITIONS[relation_type]
    change_kind = str(resolved_case.change_kind)
    directionality = str(definition["directionality"])
    semantics = str(definition["semantics"])
    target_chunk_id = _target_chunk_id(resolved_case)
    from_entity = _resolve_case_entity(
        session,
        run_id=annotation.run_id,
        name=resolved_case.from_entity or "",
        entities_by_name=entities_by_name,
        allowed_types=tuple(definition["from_types"]),
        chunk_id=target_chunk_id,
    )
    to_entity = _resolve_case_entity(
        session,
        run_id=annotation.run_id,
        name=resolved_case.to_entity or "",
        entities_by_name=entities_by_name,
        allowed_types=tuple(definition["to_types"]),
        chunk_id=target_chunk_id,
    )
    if int(from_entity.entity_id) == int(to_entity.entity_id):
        raise ValueError(f"fact 动作两端解析为同一实体: {resolved_case.case_id}")
    from_id = int(from_entity.entity_id)
    to_id = int(to_entity.entity_id)
    relation_id = _relation_id(
        annotation.run_id,
        from_id,
        to_id,
        relation_type,
        directionality,
    )
    existing = session.get(GraphRelation, relation_id)
    if existing is None:
        if change_kind != "assert":
            raise ValueError(
                "fact 动作变化未匹配到已有关系: "
                f"{resolved_case.from_entity} {relation_type} {resolved_case.to_entity}"
            )
        session.add(
            GraphRelation(
                relation_id=relation_id,
                run_id=annotation.run_id,
                from_entity_id=from_id,
                to_entity_id=to_id,
                directionality=directionality,
                relation_semantics=semantics,
            )
        )
        session.flush()
        relation = session.get(GraphRelation, relation_id)
        if relation is None:
            raise ValueError(f"关系创建失败: {relation_id}")
        draft, current_version = _latest_relation_draft(
            session,
            run_id=annotation.run_id,
            relation=relation,
            relation_type=relation_type,
            attributes={},
        )
    else:
        draft, current_version = _latest_relation_draft(
            session,
            run_id=annotation.run_id,
            relation=existing,
            relation_type=relation_type,
            attributes={},
        )
    content = {
        "kind": "relation",
        "chunk_id": target_chunk_id,
        "from_entity": _entity_descriptor(from_entity),
        "to_entity": _entity_descriptor(to_entity),
        "relation_type": relation_type,
        "change_kind": change_kind,
        "relation_id": relation_id,
        "directionality": directionality,
        "relation_semantics": semantics,
        "reason": resolved_case.reason,
    }
    fact_id = str(
        uuid5(NAMESPACE_URL, f"noveliq:case-resolution:{annotation.run_id}:{relation_id}")
    )
    fact = GraphFact(
        graph_version_id=graph_version.graph_version_id,
        run_id=annotation.run_id,
        chapter_id=annotation.chapter_id,
        fact_id=fact_id,
        fact_revision=_next_fact_revision(session, annotation.run_id, fact_id),
        fact_type="relation",
        subject_entity_id=from_id,
        predicate=relation_type,
        object=_entity_descriptor(to_entity),
        value=None,
        participants=[
            {"role": "from", "entity": _entity_descriptor(from_entity)},
            {"role": "to", "entity": _entity_descriptor(to_entity)},
        ],
        story_time=None,
        assertion="affirmed",
        confidence="high",
        content=content,
        scope=f"chapter:{annotation.chapter_id}:chunk:{target_chunk_id}",
        effective_chunk_id=target_chunk_id,
        source_kind="case_resolution",
        annotation_id=annotation.annotation_id,
        payload_path=f"case_resolution/{resolved_case.case_id}",
    )
    session.add(fact)
    session.flush()
    _apply_relation_change(
        draft=draft,
        fact=fact,
        change_kind=change_kind,
        relation_type=relation_type,
    )
    if current_version is not None and current_version.graph_version_id == graph_version.graph_version_id:
        # 2026-08-12 同一章内 chunk relations 已断言该边（或更早的案例已解决）：
        # 最新版本行已属于当前 graph_version，(graph_version_id, relation_id) 唯一约束
        # 禁止再插一行，这里直接折叠本次变化进现有版本行（同一 session 对象原地更新）
        current_version.relation_type = draft.relation_type
        current_version.attributes = draft.attributes
        current_version.is_active = draft.is_active
        current_version.changes = [*current_version.changes, *draft.changes]
    else:
        session.add(
            GraphRelationVersion(
                graph_version_id=graph_version.graph_version_id,
                run_id=annotation.run_id,
                chapter_id=graph_version.chapter_id,
                relation_id=relation_id,
                relation_revision=draft.previous_revision + 1,
                relation_type=draft.relation_type,
                attributes=draft.attributes,
                is_active=draft.is_active,
                changes=draft.changes,
            )
        )
    session.flush()
    return fact


def _persist_foreshadowing_resolution(
    session: Session,
    *,
    run_id: str,
    resolved_case: ResolvedCase,
) -> ForeshadowingThread:
    """2026-08-11 用于把 foreshadowing 动作解决结果更新到伏笔线程（setup_id 定位）"""
    setup_id = resolved_case.target_ref.get("setup_id")
    if not setup_id:
        raise ValueError(f"foreshadowing 动作案例缺少伏笔线程目标: {resolved_case.case_id}")
    thread = session.get(ForeshadowingThread, str(setup_id))
    if thread is None or thread.run_id != run_id:
        raise ValueError(f"案例目标伏笔线程不存在或跨 run: {resolved_case.case_id}")
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
    thread.updated_at = datetime.now(UTC)
    session.flush()
    return thread


def _persist_resolved_cases(
    session: Session,
    *,
    annotation: ChapterAnnotationRecord,
    graph_version: GraphVersion,
    resolved_cases: list[ResolvedCase],
    authorized_text_chunk_ids: set[int],
    entities_by_name: dict[str, GraphEntity],
) -> dict[str, Any]:
    """2026-08-11 用于按案例动作分派解决（dialogue 改对话表 / fact 改图 / foreshadowing 写线程 / close 无目标）"""
    payload = BoundChapterAnnotation.model_validate(annotation.payload)
    allowed_chunk_ids = authorized_text_chunk_ids | {
        chunk.chunk_id for chunk in payload.chunks
    }
    targets_by_case_id: dict[str, Any] = {}
    for resolved_case in resolved_cases:
        target_chunk_id = _target_chunk_id(resolved_case)
        if target_chunk_id not in allowed_chunk_ids:
            raise ValueError(
                "resolve_case 使用了未经系统读取授权的原文: "
                f"{target_chunk_id}"
            )
        target: Any = None
        if resolved_case.action == "dialogue":
            target = _persist_dialogue_resolution(
                session,
                run_id=annotation.run_id,
                resolved_case=resolved_case,
            )
        elif resolved_case.action == "fact":
            target = _persist_fact_resolution(
                session,
                annotation=annotation,
                graph_version=graph_version,
                resolved_case=resolved_case,
                entities_by_name=entities_by_name,
            )
        elif resolved_case.action == "foreshadowing":
            target = _persist_foreshadowing_resolution(
                session,
                run_id=annotation.run_id,
                resolved_case=resolved_case,
            )
        elif resolved_case.action == "close":
            target = None
        else:
            raise ValueError(f"未知案例动作: {resolved_case.action}")
        targets_by_case_id[resolved_case.case_id] = target
    return targets_by_case_id


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

    entities_by_name, attribute_patches = _resolve_entities(
        session,
        annotation=annotation,
        payload=payload,
    )
    facts, attribute_changes = _persist_annotation_facts(
        session,
        annotation=annotation,
        payload=payload,
        graph_version=graph_version,
        chapter_order=chapter_order,
        entities_by_name=entities_by_name,
        attribute_patches=attribute_patches,
    )
    _persist_state_versions(
        session,
        graph_version=graph_version,
        chapter_order=chapter_order,
        facts=facts,
        entities_by_name=entities_by_name,
        attribute_changes=attribute_changes,
    )
    _persist_relation_versions(
        session,
        graph_version=graph_version,
        chapter_order=chapter_order,
        facts=facts,
    )
    resolved_targets = _persist_resolved_cases(
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
        resolved_targets_by_case_id=resolved_targets,
    )
