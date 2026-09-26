"""章节标注到图谱当前状态的原子写入"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents.annotation.fact_graph import _entity_uuid
from src.agents.annotation.schema import (
    RELATION_DEFINITIONS,
    BoundChapterAnnotation,
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


def run_entities_by_name(session: Session, *, run_id: str) -> dict[str, GraphEntity]:
    """2026-09-17 用于按规范化名称装载一次运行的全部图实体（名称解析的唯一索引口径）"""
    return {
        _normalized_name(entity.canonical_name): entity
        for entity in session.execute(select(GraphEntity).where(GraphEntity.run_id == run_id)).scalars()
    }


def resolve_character_entity(
    session: Session,
    *,
    run_id: str,
    name: str,
    chapter_id: int,
    entities: dict[str, GraphEntity],
) -> GraphEntity | None:
    """2026-09-17 用于把对话说话人的登记名解析成图实体（说话人存 id 的唯一解析口）

    说话人可能是**本章**才登记的实体，而实体行由完成事务里的 _resolve_entities 创建；
    对话行先于它写入，所以查不到就按 character 建一条最小行，随后 _resolve_entities
    命中同一行再做属性/tags 合并（与 _resolve_case_entity 同一策略）。
    解析到的行不是 character 时返回 None——调用方置空该说话人并告警，
    不因此阻断整章完成事务（说话人本来就允许缺省）。

    传入的 entities 是可变索引（调用方按章装载一次），新建的行会写回其中。
    """
    key = _normalized_name(name)
    entity = entities.get(key)
    if entity is None:
        entity = GraphEntity(
            entity_id=_entity_uuid(run_id, key),
            run_id=run_id,
            canonical_name=name,
            entity_type="character",
            tags=[],
            attributes={"entity_type": "character"},
            first_seen_chapter=chapter_id,
            last_seen_chapter=chapter_id,
        )
        session.add(entity)
        session.flush()
        entities[key] = entity
    if str(entity.entity_type) != "character":
        logger.warning(
            "对话说话人已登记为非 character，置空该说话人: run_id={} name={} entity_type={}",
            run_id,
            name,
            entity.entity_type,
        )
        return None
    entity.last_seen_chapter = max(int(entity.last_seen_chapter), chapter_id)
    return entity


def stable_annotation_fact_id(annotation_id: str, chapter_id: int, domain: str, ordinal: int) -> str:
    """2026-08-19 用于按章节标注位置生成稳定事实 ID"""
    return str(uuid5(UUID(annotation_id), f"{chapter_id}:{domain}:{ordinal}"))


def _relation_id(
    run_id: str,
    from_entity_id: str,
    to_entity_id: str,
    relation_type: str,
    directionality: str,
) -> str:
    """2026-08-19 用于根据实体端点和关系语义生成稳定关系 ID

    2026-09-19 端点改 uuid 后双向归一取字典序较小端（字符串比较，确定性不变）。
    """
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
        }
    ]


def _event_text_evidence_by_node(
    session: Session,
    *,
    annotation: ChapterAnnotationRecord,
    payload: BoundChapterAnnotation,
    chapter_evidence: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """为新事件取精确段落区间；已有 0.1.0 载荷保留原章级锚点。"""
    paragraph_ids = {event.evidence_paragraph_id for event in payload.events if event.evidence_paragraph_id is not None}
    paragraphs = (
        session.execute(
            select(Paragraph).where(
                Paragraph.run_id == annotation.run_id,
                Paragraph.chapter_id == annotation.chapter_id,
                Paragraph.paragraph_id.in_(paragraph_ids),
            )
        ).scalars().all()
        if paragraph_ids
        else []
    )
    by_id = {int(row.paragraph_id): row for row in paragraphs}
    if missing := paragraph_ids - by_id.keys():
        raise ValueError(f"事件证据不属于当前章节: paragraph_ids={sorted(missing)}")
    return {
        event.node_id: (
            dict(chapter_evidence)
            if event.evidence_paragraph_id is None
            else {
                "paragraph_ids": [event.evidence_paragraph_id],
                "char_start": int(by_id[event.evidence_paragraph_id].local_start_char),
                "char_end": int(by_id[event.evidence_paragraph_id].local_end_char),
            }
        )
        for event in payload.events
    }


def _entity_attributes(entity: dict[str, Any], entity_type: EntityType) -> dict[str, Any]:
    """2026-08-19 用于提取实体本次提交的属性

    2026-09-04 单一写面：输入从 BoundEntity 副本改为 FactGraph entity_ops 单条操作。
    """
    attributes: dict[str, Any] = {"entity_type": entity_type}
    if entity.get("description") is not None:
        attributes["description"] = entity["description"]
    attributes.update(entity.get("attributes") or {})
    return attributes


def _resolve_entities(
    session: Session,
    *,
    annotation: ChapterAnnotationRecord,
    entity_ops: list[dict[str, Any]],
) -> tuple[dict[str, GraphEntity], dict[str, list[dict[str, Any]]]]:
    """2026-08-19 用于按规范化名称匹配或创建实体并记录属性变化

    2026-09-04 单一写面：输入从 payload 的实体目录副本改为 FactGraph 的 entity_ops
    操作日志（write_entity 按提交顺序追加）；同名属性合并、tags 去重拼接、
    before/after 审计的语义与原实现一致。
    2026-09-19 实体行显式带 uuid5(run+规范名) 主键（与 agent 运行面同 id）。
    """
    appearances: dict[str, list[tuple[int, EntityType, dict[str, Any]]]] = {}
    display_names: dict[str, str] = {}
    for op in entity_ops:
        name = str(op["name"])
        key = _normalized_name(name)
        if key in display_names and display_names[key] != name:
            raise ValueError(f"实体名称规范化后冲突: {display_names[key]} / {name}")
        display_names[key] = name
        appearances.setdefault(key, []).append(
            (int(op["chapter_id"]), cast(EntityType, str(op["entity_type"])), op)
        )
    existing = run_entities_by_name(session, run_id=annotation.run_id)
    resolved: dict[str, GraphEntity] = {}
    patches: dict[str, list[dict[str, Any]]] = {}
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
            tags.extend(tag for tag in item.get("tags") or [] if tag not in tags)
        entity = existing.get(key)
        if entity is not None and entity.entity_type != entity_type:
            raise ValueError(f"实体名称已属于其他大类: {display_names[key]}")
        if entity is None:
            entity = GraphEntity(
                entity_id=_entity_uuid(annotation.run_id, key),
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
                    patches.setdefault(entity.entity_id, []).append(
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
        "entity_id": str(entity.entity_id),
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
        resolved_payload_path = f"chapters/{chapter_id}/{domain}/{ordinal}"
    return GraphFact(
        run_id=annotation.run_id,
        chapter_id=chapter_id,
        fact_id=resolved_fact_id,
        fact_type=domain,
        subject_entity_id=str(subject.entity_id) if subject is not None else None,
        predicate=predicate,
        object=object_value,
        value=value,
        participants=participants,
        scope=f"chapter:{annotation.chapter_id}",
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


def _previous_state(session: Session, *, run_id: str, entity_id: str, chapter_order: int) -> dict[str, Any]:
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
    attribute_changes: dict[str, list[dict[str, Any]]],
) -> None:
    """2026-08-19 用于按章节写入实体状态行并继承前序状态"""
    entity_by_id = {entity.entity_id: entity for entity in entities.values()}
    updates_by_entity: dict[str, list[dict[str, Any]]] = {}
    for fact in facts:
        if fact.subject_entity_id is not None:
            updates = _state_updates(fact)
            if updates:
                updates_by_entity.setdefault(fact.subject_entity_id, []).append(
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


def _relation_key(from_id: str, to_id: str, relation_type: str, directionality: str) -> tuple[str, str, str, str]:
    """2026-08-19 用于生成关系状态查找键（uuid 端点按字典序归一，确定性不变）"""
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
    payload: BoundChapterAnnotation,
    entities: dict[str, GraphEntity],
    event_evidence_by_node: dict[str, dict[str, Any]],
) -> dict[int, str]:
    """2026-08-19 用于写入事件节点及当前章节因果边

    2026-08-22event_id 直接取服务端生成的 node_id；因果边只存在于
    跨章树根（cause_tree_id），由 write_event 结构性保证无环，DAG 校验删除。
    新事件使用所在段证据；已有 0.1.0 载荷仍按原章级证据读取。
    2026-09-14 跨章因果链退役：write_event 不再产生 causal refs，causal 边无新来源
    （列与边类型保留读旧数据）；伏笔属性只剩 payoff_likelihood（三档）。
    """
    event_ids: dict[int, str] = {}
    for index, event in enumerate(payload.events, start=1):
        event_id = event.node_id
        event_ids[index] = event_id
        event_evidence = event_evidence_by_node[event_id]
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
                    chapter_id=annotation.chapter_id,
                    chapter_order=boundary.chapter_order,
                    description=event.description,
                    participants=participants,
                    anchor_paragraph_ids=list(event_evidence["paragraph_ids"]),
                    char_start=int(event_evidence["char_start"]),
                    char_end=int(event_evidence["char_end"]),
                    evidence=[dict(event_evidence)],
                    causal_event_refs=[],
                    tree_id=event.tree_id,
                    cause_role=event.cause_role,
                    is_foreshadowing_root=event.is_foreshadow_setup,
                    foreshadowing_status="open" if event.is_foreshadow_setup else None,
                    payoff_likelihood=str(event.payoff_likelihood) if event.payoff_likelihood else None,
                    annotation_id=annotation.annotation_id,
                    source_kind="annotation",
                    payload_path=f"chapters/{annotation.chapter_id}/events/{index}",
                )
            )
    session.flush()
    return event_ids


def _persist_annotation_facts(
    session: Session,
    *,
    annotation: ChapterAnnotationRecord,
    boundary: ChapterBoundary,
    payload: BoundChapterAnnotation,
    entities: dict[str, GraphEntity],
    attribute_changes: dict[str, list[dict[str, Any]]],
    relation_assert_ops: list[dict[str, Any]],
) -> list[GraphFact]:
    """2026-08-19 用于写入当前章节事实、事件和关系状态

    2026-09-04 单一写面：关系 assert 事实的输入从 payload 副本改为 FactGraph
    操作日志 relation_assert_ops（按 chapter_id 归属到章）。
    """
    facts: list[GraphFact] = []
    relation_drafts: dict[str, _RelationDraft] = {}
    if True:
        evidence = _chapter_text_evidence(session, run_id=annotation.run_id, chapter_id=annotation.chapter_id)
        event_evidence_by_node = _event_text_evidence_by_node(
            session, annotation=annotation, payload=payload, chapter_evidence=evidence[0]
        )
        event_ids = _persist_event_nodes(
            session,
            annotation=annotation,
            boundary=boundary,
            payload=payload,
            entities=entities,
            event_evidence_by_node=event_evidence_by_node,
        )
        for ordinal, observation in enumerate(payload.character_observations, start=1):
            subject = _entity(entities, observation.character)
            facts.append(
                _new_fact(
                    annotation=annotation,
                    chapter_id=annotation.chapter_id,
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
                        "chapter_id": annotation.chapter_id,
                        "entity": _entity_descriptor(subject),
                        "role_function": observation.role_function,
                        "action": observation.action,
                        "emotion": observation.emotion,
                    },
                    evidence=evidence,
                )
            )
        for ordinal, event in enumerate(payload.events, start=1):
            event_evidence = [event_evidence_by_node[event.node_id]]
            participants = [
                {"role": participant.role, "entity": _entity_descriptor(_entity(entities, participant.entity))}
                for participant in event.participants
            ]
            facts.append(
                _new_fact(
                    annotation=annotation,
                    chapter_id=annotation.chapter_id,
                    domain="event",
                    ordinal=ordinal,
                    subject=_entity(entities, event.participants[0].entity) if event.participants else None,
                    predicate="event",
                    object_value=None,
                    value={"description": event.description},
                    participants=participants,
                    content={
                        "kind": "event",
                        "chapter_id": annotation.chapter_id,
                        "description": event.description,
                        "anchor_paragraph_ids": list(event_evidence[0]["paragraph_ids"]),
                    },
                    evidence=event_evidence,
                    event_id=event_ids[ordinal],
                )
            )
        # 2026-09-04 单一写面：关系 assert 事实从 FactGraph 操作日志派生，
        # 不再读 payload.relations 副本；端点名取每次重放前已解析的规范名
        for ordinal, relation_item in enumerate(
            [op for op in relation_assert_ops if int(op["chapter_id"]) == annotation.chapter_id],
            start=1,
        ):
            from_entity = _entity(entities, str(relation_item["from_entity"]))
            to_entity = _entity(entities, str(relation_item["to_entity"]))
            if from_entity is None or to_entity is None:
                raise ValueError("relation 端点缺少实体")
            relation_type = str(relation_item["relation_type"])
            definition = RELATION_DEFINITIONS[relation_type]
            relation_id = _relation_id(
                annotation.run_id,
                str(from_entity.entity_id),
                str(to_entity.entity_id),
                relation_type,
                str(definition["directionality"]),
            )
            relation = session.get(GraphRelation, relation_id)
            if relation is None:
                relation = GraphRelation(
                    relation_id=relation_id,
                    run_id=annotation.run_id,
                    from_entity_id=str(from_entity.entity_id),
                    to_entity_id=str(to_entity.entity_id),
                    directionality=str(definition["directionality"]),
                    relation_semantics=str(definition["semantics"]),
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
                    relation_type=relation_type,
                    current_chapter_id=annotation.chapter_id,
                ),
            )
            change_kind = "assert" if not draft.is_active else "noop"
            fact = _new_fact(
                annotation=annotation,
                chapter_id=annotation.chapter_id,
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
                content={
                    "kind": "relation",
                    "chapter_id": annotation.chapter_id,
                    "relation_id": relation_id,
                    "relation_type": relation_type,
                    "change_kind": change_kind,
                },
                evidence=evidence,
            )
            facts.append(fact)
            _apply_relation_change(
                draft, fact=fact, change_kind=change_kind, relation_type=relation_type
            )
    for entity_id, changes in attribute_changes.items():
        for ordinal, change in enumerate(changes, start=1):
            entity = next((item for item in entities.values() if item.entity_id == entity_id), None)
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
                payload_path=(f"chapters/{chapter_for_fact}/entity_attribute/{entity_id}/{ordinal}"),
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
        entity_id=_entity_uuid(run_id, _normalized_name(name)),
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
    """2026-08-19 用于读取案例登记时的章节锚点

    2026-09-18 无案例的写入动作（case_id 为空）没有案例锚点，由调用方按当前章处理。
    """
    chapter_id = resolved_case.target_ref.get("chapter_id")
    if chapter_id is None:
        raise ValueError(f"案例目标缺少章节 ID: {resolved_case.case_id}")
    return int(chapter_id)


def _persist_dialogue_resolution(
    session: Session,
    *,
    run_id: str,
    resolved_case: ResolvedCase,
    entities: dict[str, GraphEntity],
) -> DialogueRecord:
    """2026-08-19 用于把 dialogue 动作更新到对话记录

    2026-09-17 说话人存 id：模型面给的登记名在这里解析成图实体行（见 resolve_character_entity），
    解析不到 character 就保留原说话人不覆盖。
    2026-09-18 无案例的更新（case_id 空，写入路径自己发起）走同一条路：目标仍是
    target_ref 里的对话记录键（candidate_key），报错文案按目标键点出。
    """
    candidate_key = resolved_case.target_ref.get("candidate_key")
    record = session.execute(
        select(DialogueRecord).where(
            DialogueRecord.run_id == run_id, DialogueRecord.candidate_key == str(candidate_key)
        )
    ).scalar_one_or_none()
    if record is None:
        raise ValueError(f"对话记录不存在: {candidate_key}（案例 {resolved_case.case_id or '写入路径'}）")
    if resolved_case.speaker is not None:
        speaker_entity = resolve_character_entity(
            session,
            run_id=run_id,
            name=str(resolved_case.speaker),
            chapter_id=_target_chapter_id(resolved_case),
            entities=entities,
        )
        if speaker_entity is not None:
            record.speaker = str(speaker_entity.entity_id)
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
    """2026-08-19 用于把 fact 动作写成章节关系事实和状态

    2026-09-18 无案例的关系变化（case_id 空，写入路径自己发起）没有案例 id 可做唯一键：
    fact_id 改由章 + 本条变更在本章变更日志里的序号派生（target_ref["change_index"]），
    否则同章多条无案例变更会撞同一个 fact_id；来源标记也随之改写成 write_path。
    """
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
        str(from_entity.entity_id),
        str(to_entity.entity_id),
        relation_type,
        str(definition["directionality"]),
    )
    relation = session.get(GraphRelation, relation_id)
    if relation is None:
        relation = GraphRelation(
            relation_id=relation_id,
            run_id=annotation.run_id,
            from_entity_id=str(from_entity.entity_id),
            to_entity_id=str(to_entity.entity_id),
            directionality=str(definition["directionality"]),
            relation_semantics=str(definition["semantics"]),
        )
        session.add(relation)
        session.flush()
    case_driven = bool(resolved_case.case_id)
    fact = GraphFact(
        run_id=annotation.run_id,
        chapter_id=annotation.chapter_id,
        fact_id=(
            str(uuid5(NAMESPACE_URL, f"noveliq:case:{annotation.run_id}:{resolved_case.case_id}"))
            if case_driven
            else str(
                uuid5(
                    NAMESPACE_URL,
                    f"noveliq:change:{annotation.run_id}:{annotation.chapter_id}:"
                    f"{resolved_case.target_ref.get('change_index')}",
                )
            )
        ),
        fact_type="relation",
        subject_entity_id=str(from_entity.entity_id),
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
        source_kind="case_resolution" if case_driven else "write_path",
        annotation_id=annotation.annotation_id,
        payload_path=(
            f"case_resolution/{resolved_case.case_id}"
            if case_driven
            else f"relation_change/{annotation.chapter_id}/{resolved_case.target_ref.get('change_index')}"
        ),
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
    annotation_id: str,
    resolved_case: ResolvedCase,
) -> dict[str, Any]:
    """2026-09-13 用于把 foreshadowing 动作落成伏笔树挂边（伏笔即事件树）

    解决动作 = 把挂树事件用 foreshadowing 边接进伏笔树（source=根/埋设事件，
    target=挂入事件）；payoff 同时把根状态收束为 likely_paid_off，reinforce 把
    open 根推进为 reinforced。可选更新根属性 payoff_likelihood/strength
    （2026-09-14 expected_payoff_family 退役）。同端点 foreshadowing 边已存在时幂等跳过建边。
    """
    root_event_id = str(resolved_case.foreshadowing_root_event_id)
    event_id = str(resolved_case.foreshadowing_event_id)
    root = session.get(EventNode, root_event_id)
    if root is None or root.run_id != run_id or not root.is_foreshadowing_root:
        raise ValueError(f"伏笔树根不存在或非伏笔根: {resolved_case.case_id or root_event_id}")
    node = session.get(EventNode, event_id)
    if node is None or node.run_id != run_id:
        raise ValueError(f"挂树事件不存在或跨 run: {resolved_case.case_id or event_id}")
    if resolved_case.payoff_likelihood is not None:
        root.payoff_likelihood = resolved_case.payoff_likelihood
    if resolved_case.strength is not None:
        root.strength = resolved_case.strength
    if resolved_case.foreshadowing_action == "payoff":
        root.foreshadowing_status = "likely_paid_off"
    elif root.foreshadowing_status == "open":
        root.foreshadowing_status = "reinforced"
    edge_id = _event_edge_id(run_id, root_event_id, event_id)
    if session.get(EventEdge, edge_id) is None:
        session.add(
            EventEdge(
                edge_id=edge_id,
                run_id=run_id,
                edge_type="foreshadowing",
                source_event_id=root_event_id,
                target_event_id=event_id,
                source_chapter_id=root.chapter_id,
                target_chapter_id=node.chapter_id,
                is_active=True,
                evidence=list(root.evidence),
                annotation_id=annotation_id,
                payload_path=f"foreshadowing/{root_event_id}/{event_id}",
            )
        )
    session.flush()
    return {
        "root": root,
        "target_root_event_id": root_event_id,
        "target_event_id": event_id,
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
    """2026-08-19 用于按案例动作分派解决并校验章节授权

    2026-09-18 无案例的条目（case_id 空，写入路径自己发起的变化）按本章处理，不做案例锚点的
    读取授权校验——它是本次写入的一部分，不涉及读别的章节。
    """
    targets: dict[str, Any] = {}
    allowed_chapter_ids = set(authorized_text_chapter_ids) | {annotation.chapter_id}
    for resolved_case in resolved_cases:
        target_chapter_id = (
            _target_chapter_id(resolved_case) if resolved_case.case_id else annotation.chapter_id
        )
        if target_chapter_id not in allowed_chapter_ids:
            raise ValueError(f"resolve_case 使用了未经系统读取授权的章节: {target_chapter_id}")
        target: Any
        if resolved_case.action == "dialogue":
            target = _persist_dialogue_resolution(
                session,
                run_id=annotation.run_id,
                resolved_case=resolved_case,
                entities=entities,
            )
        elif resolved_case.action == "fact":
            target = _persist_fact_resolution(
                session, annotation=annotation, boundary=boundary, resolved_case=resolved_case, entities=entities
            )
        elif resolved_case.action == "foreshadowing":
            target = _persist_foreshadowing_resolution(
                session, run_id=annotation.run_id, annotation_id=annotation.annotation_id, resolved_case=resolved_case
            )
        elif resolved_case.action == "close":
            target = None
        elif resolved_case.action == "promise":
            # 2026-09-18 promise 动作只记「案例由哪条产出记录交代」：记录已由写入路径
            # 落库，此处不改图也不改记录（记录键随 resolution 写进映射表）
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
    entity_ops: list[dict[str, Any]],
    relation_assert_ops: list[dict[str, Any]],
    authorized_text_chapter_ids: set[int],
    authorized_text_paragraph_ids: set[int] | None = None,
) -> PersistedGraphResult:
    """2026-08-20 扁平化图谱持久化链，内联章节边界生成和标注校验逻辑

    2026-09-04 单一写面：实体与关系 assert 事实的输入是 FactGraph 操作日志
    （entity_ops / relation_assert_ops），不再从 payload 图副本读取；
    fact 裁决由存储边界从 relation_change_ops 还原为 ResolvedCase 传入。
    """
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

    # 2026-08-22 重构：证据升为章级单份，事件节点只携带树结构；
    # 模型零结构输入后不再存在节点级锚点/哈希可校验，
    # 校验本章原文与段落事实源齐备；具体事件证据在 _persist_annotation_facts 中绑定。
    _chapter_text_evidence(session, run_id=annotation.run_id, chapter_id=annotation.chapter_id)

    # 继续原有逻辑
    entities, attribute_changes = _resolve_entities(session, annotation=annotation, entity_ops=entity_ops)
    facts = _persist_annotation_facts(
        session,
        annotation=annotation,
        boundary=boundary,
        payload=payload,
        entities=entities,
        attribute_changes=attribute_changes,
        relation_assert_ops=relation_assert_ops,
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
