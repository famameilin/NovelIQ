"章节图谱查询仓储：实体与关系状态从正式贡献按章序、角色序、操作序折叠"

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.models import (
    Agent,
    Chapter,
    ChapterAnnotation,
    CompleteEvent,
    EventParticipant,
    FactEntityTag,
    GraphEntity,
    GraphFact,
    GraphRelation,
)
from src.storage.records.graph import (
    ChapterBoundary,
    EntitySnapshotRow,
    GraphChangeRow,
    GraphSnapshotRow,
    RelationSnapshotRow,
)
from src.storage.repositories.base import BaseRepository


def _display_relation_change(change: dict[str, Any], *, from_name: str | None, to_name: str | None) -> dict[str, Any]:
    "关系变化读侧展示：操作日志端点存的是实体身份键，按登记名回显"
    item = dict(change)
    operation = item.get("operation")
    if not isinstance(operation, dict):
        return item
    if "from_entity" not in operation and "to_entity" not in operation:
        return item
    display = dict(operation)
    if from_name is not None:
        display["from_entity"] = from_name
    if to_name is not None:
        display["to_entity"] = to_name
    item["operation"] = display
    return item


class GraphRepository(BaseRepository[GraphFact]):
    def __init__(self, session: Session, *, internal: bool = False) -> None:
        super().__init__(session)
        self.internal = internal

    def run_exists(self, run_id: str) -> bool:
        from src.storage.models import Run

        return self.session.get(Run, run_id) is not None

    def _require_visible(self, run_id: str) -> None:
        "只有释放事务内部可绕过最终边界，普通查询不能读未发布的物化状态"
        if not self.run_exists(run_id):
            raise ValueError(f"run_id={run_id} 不存在")

    def _chapter_rows(self, run_id: str) -> list[Chapter]:
        "用于读取当前运行的有正文章节并确定顺序"
        self._require_visible(run_id)
        return list(
            self.session.execute(
                select(Chapter)
                .where(Chapter.run_id == run_id, Chapter.text.isnot(None))
                .order_by(Chapter.sequence, Chapter.chapter_id)
            ).scalars()
        )

    def _chapter_order_map(self, run_id: str) -> dict[int, int]:
        "用于把章节身份映射为历史排序"
        return {int(chapter.chapter_id): int(chapter.sequence) for chapter in self._chapter_rows(run_id)}

    def _records_by_chapter(self, run_id: str) -> dict[int, str]:
        "用于读取每章已成功保存的正式标注产物身份（章内多角色取最后一份）"
        records: dict[int, str] = {}
        for chapter_id, record_id in self.session.execute(
            select(ChapterAnnotation.chapter_id, ChapterAnnotation.record_id)
            .where(ChapterAnnotation.run_id == run_id)
            .order_by(ChapterAnnotation.saved_at, ChapterAnnotation.record_id)
        ):
            records[int(chapter_id)] = str(record_id)
        return records

    def resolve_chapter_boundary(self, run_id: str, *, chapter_id: int | None = None) -> ChapterBoundary | None:
        "用于解析显式章节或当前运行最后章节"
        chapters = self._chapter_rows(run_id)
        records = self._records_by_chapter(run_id)
        target = (
            next((chapter for chapter in reversed(chapters) if chapter.chapter_id in records), None)
            if chapter_id is None
            else next((chapter for chapter in chapters if chapter.chapter_id == chapter_id), None)
        )
        if target is None or target.chapter_id not in records:
            return None
        return ChapterBoundary(
            run_id=run_id,
            chapter_id=target.chapter_id,
            chapter_order=int(target.sequence),
            first_chapter_id=target.chapter_id,
            last_chapter_id=target.chapter_id,
            annotation_id=records[target.chapter_id],
        )

    def resolve_persisted_boundary(self, run_id: str) -> ChapterBoundary | None:
        "用于构造覆盖全部已提交数据的历史边界（不依赖 annotation record）"
        chapters = self._chapter_rows(run_id)
        if not chapters:
            return None
        return ChapterBoundary(
            run_id=run_id,
            chapter_id=int(chapters[-1].chapter_id),
            chapter_order=int(chapters[-1].sequence),
            first_chapter_id=int(chapters[0].chapter_id),
            last_chapter_id=int(chapters[-1].chapter_id),
            annotation_id="",
        )

    def _fold_graph(self, run_id: str) -> _FoldedGraph:
        "按原始贡献序折叠实体与关系状态；事实序 =（章序、角色序、执行、列表内序）"
        chapters = self._chapter_rows(run_id)
        order_map = {int(chapter.chapter_id): int(chapter.sequence) for chapter in chapters}
        entities = {
            str(row.entity_id): row
            for row in self.session.execute(select(GraphEntity).where(GraphEntity.run_id == run_id)).scalars()
        }
        direct_rows = list(
            self.session.execute(
                select(GraphFact, Agent.id, ChapterAnnotation.chapter_id, Agent.type)
                .join(Agent, Agent.id == GraphFact.direct_producer_agent_id)
                .outerjoin(ChapterAnnotation, ChapterAnnotation.agent_id == Agent.id)
                .where(
                    GraphFact.direct_producer_agent_id.is_not(None),
                    Agent.run_id == run_id,
                )
            )
        )
        participant_rows = list(
            self.session.execute(
                select(
                    GraphFact,
                    EventParticipant.entity_id,
                    EventParticipant.narrative_role,
                    EventParticipant.action,
                    EventParticipant.emotion,
                    Agent.id,
                    ChapterAnnotation.chapter_id,
                    Agent.type,
                )
                .join(EventParticipant, EventParticipant.participant_id == GraphFact.participant_id)
                .join(CompleteEvent, CompleteEvent.event_id == EventParticipant.event_id)
                .join(ChapterAnnotation, ChapterAnnotation.record_id == CompleteEvent.annotation_record_id)
                .join(Agent, Agent.id == ChapterAnnotation.agent_id)
                .where(GraphFact.participant_id.is_not(None), ChapterAnnotation.run_id == run_id)
            )
        )
        role_order = {"annotation": 0, "entity": 0, "event": 1, "metric": 2, "case": 3, "report": 3}
        entry: list[tuple[tuple[Any, ...], str, int | None, str, Any]] = []
        for fact, agent_id, execution_chapter, role in direct_rows:
            chapter_id = fact.effective_chapter_id if fact.effective_chapter_id is not None else execution_chapter
            sort_key: tuple[Any, ...] = (
                order_map.get(int(chapter_id), 10**9) if chapter_id is not None else 10**9,
                role_order.get(str(role), 3),
                str(agent_id),
                0,
                int(fact.operation_order or 0),
            )
            entry.append((sort_key, str(fact.graph_fact_id), chapter_id, str(agent_id), fact))
        for fact, entity_id, narrative_role, action, emotion, agent_id, record_chapter, role in participant_rows:
            sort_key = (
                order_map.get(int(record_chapter), 10**9) if record_chapter is not None else 10**9,
                role_order.get(str(role), 3),
                str(agent_id),
                1,
                str(fact.graph_fact_id),
            )
            entry.append(
                (
                    sort_key,
                    str(fact.graph_fact_id),
                    record_chapter,
                    str(agent_id),
                    (fact, str(entity_id), narrative_role, action, emotion),
                )
            )
        entry.sort(key=lambda item: item[0])
        tags_by_fact: dict[str, list[str]] = {}
        fact_ids = [item[1] for item in entry]
        if fact_ids:
            for tag in self.session.execute(
                select(FactEntityTag).where(FactEntityTag.graph_fact_id.in_(fact_ids))
            ).scalars():
                tags_by_fact.setdefault(str(tag.graph_fact_id), []).append(str(tag.tag))
        relations = {str(row.relation_id): row for row in self.session.execute(select(GraphRelation)).scalars()}
        folded = _FoldedGraph(order_map=order_map)
        entity_values: dict[str, dict[str, Any]] = {}
        tag_sources: dict[tuple[int, str], dict[str, list[str]]] = {}
        support_counts: dict[str, int] = {}
        touched: dict[str, list[int]] = {}
        for _sort_key, fact_id, chapter_id, author, payload in entry:
            order = order_map.get(int(chapter_id), 0) if chapter_id is not None else 0
            if isinstance(payload, tuple):
                fact, entity_id, narrative_role, action, emotion = payload
                entity = entities.get(entity_id)
                if entity is None:
                    continue
                current = entity_values.setdefault(
                    entity_id,
                    {
                        "attributes": {},
                        "tags": [],
                        "name": str(entity.canonical_name),
                        "entity_type": str(entity.entity_type),
                    },
                )
                name = str(entity.canonical_name)
                changes: list[dict[str, Any]] = []
                operation: dict[str, Any] = {"character": name}
                for field_name, value in (
                    ("role_function", narrative_role),
                    ("action", action),
                    ("emotion", emotion),
                ):
                    if value is None:
                        continue
                    before = current.get(field_name)
                    current[field_name] = value
                    operation[field_name] = value
                    changes.append(
                        {
                            "fact_id": str(fact_id),
                            "chapter_id": chapter_id,
                            "author_agent_id": author,
                            "operation": dict(operation),
                            "field": field_name,
                            "before": before,
                            "after": value,
                        }
                    )
                if order:
                    touched.setdefault(entity_id, []).append(int(chapter_id or 0))
                bucket = folded.entity_states.setdefault((int(chapter_id or 0), entity_id), _EntityStateBucket())
                bucket.state = deepcopy(current)
                bucket.changes.extend(changes)
                continue
            fact = payload
            if fact.relation_id is not None:
                relation = relations.get(str(fact.relation_id))
                if relation is None:
                    continue
                change_kind = str(fact.relation_change_kind or "assert")
                if change_kind not in {"retract", "break"}:
                    support_counts[str(fact.relation_id)] = support_counts.get(str(fact.relation_id), 0) + 1
                key = (int(chapter_id or 0), str(fact.relation_id))
                relation_bucket = folded.relation_states.get(key)
                if relation_bucket is None:
                    relation_bucket = _RelationStateBucket(relation_type=str(relation.relation_type))
                    folded.relation_states[key] = relation_bucket
                relation_bucket.is_active = change_kind not in {"retract", "break"}
                relation_bucket.attributes = {"support_count": support_counts.get(str(fact.relation_id), 0)}
                if fact.identity_kind is not None:
                    relation_bucket.attributes["identity_kind"] = str(fact.identity_kind)
                from_name = entities.get(str(relation.from_entity_id))
                to_name = entities.get(str(relation.to_entity_id))
                relation_bucket.changes.append(
                    {
                        "fact_id": str(fact_id),
                        "chapter_id": chapter_id,
                        "author_agent_id": author,
                        "operation": {
                            "from_entity": str(from_name.canonical_name) if from_name is not None else "",
                            "to_entity": str(to_name.canonical_name) if to_name is not None else "",
                            "relation_type": str(relation.relation_type),
                            "chapter_id": chapter_id,
                        },
                        "change_kind": change_kind,
                        "reason": fact.reason,
                    }
                )
                if chapter_id is not None:
                    span = folded.relation_spans.get(str(fact.relation_id))
                    folded.relation_spans[str(fact.relation_id)] = (
                        min(span[0], int(chapter_id)) if span else int(chapter_id),
                        max(span[1], int(chapter_id)) if span else int(chapter_id),
                    )
                continue
            if fact.entity_id is None:
                continue
            entity = entities.get(str(fact.entity_id))
            if entity is None:
                continue
            entity_id = str(fact.entity_id)
            name = str(entity.canonical_name)
            entity_type = str(entity.entity_type)
            # 引用身份确认（tags_submitted=False）不产生状态与变化；无字段更新按实体操作折叠
            reference_only = fact.tags_submitted is False
            current = entity_values.setdefault(
                entity_id,
                {"attributes": {}, "tags": [], "name": name, "entity_type": entity_type},
            )
            if order:
                touched.setdefault(entity_id, []).append(int(chapter_id or 0))
            if reference_only:
                continue
            before = deepcopy(current)
            changes = [
                {
                    "fact_id": str(fact_id),
                    "chapter_id": chapter_id,
                    "author_agent_id": author,
                    "operation": {"name": name, "entity_type": entity_type, "chapter_id": chapter_id},
                    "field": "entity_type",
                    "before": before.get("entity_type"),
                    "after": entity_type,
                }
            ]
            operation = {"name": name, "entity_type": entity_type, "chapter_id": chapter_id}
            if fact.description_action == "set":
                changes.append(
                    {
                        "fact_id": str(fact_id),
                        "chapter_id": chapter_id,
                        "author_agent_id": author,
                        "operation": operation,
                        "field": "description",
                        "before": before["attributes"].get("description"),
                        "after": fact.description_value,
                    }
                )
                current["attributes"]["description"] = fact.description_value
            elif fact.description_action == "clear":
                changes.append(
                    {
                        "fact_id": str(fact_id),
                        "chapter_id": chapter_id,
                        "author_agent_id": author,
                        "operation": operation,
                        "field": "description",
                        "before": before["attributes"].get("description"),
                        "after": None,
                    }
                )
                current["attributes"].pop("description", None)
            if fact.representative_action == "set":
                changes.append(
                    {
                        "fact_id": str(fact_id),
                        "chapter_id": chapter_id,
                        "author_agent_id": author,
                        "operation": operation,
                        "field": "is_representative",
                        "before": before["attributes"].get("is_representative"),
                        "after": True,
                    }
                )
                current["attributes"]["is_representative"] = True
            elif fact.representative_action == "clear":
                changes.append(
                    {
                        "fact_id": str(fact_id),
                        "chapter_id": chapter_id,
                        "author_agent_id": author,
                        "operation": operation,
                        "field": "is_representative",
                        "before": before["attributes"].get("is_representative"),
                        "after": None,
                    }
                )
                current["attributes"].pop("is_representative", None)
            if fact.tags_submitted:
                sources = tag_sources.setdefault((int(chapter_id or 0), entity_id), {})
                sources[author] = list(tags_by_fact.get(str(fact_id), []))
                current["tags"] = list(dict.fromkeys(tag for author in sorted(sources) for tag in sources[author]))
            bucket = folded.entity_states.setdefault((int(chapter_id or 0), entity_id), _EntityStateBucket())
            bucket.state = deepcopy(current)
            bucket.changes.extend(changes)
        for entity_id, chapters_touched in touched.items():
            orders = [(order_map.get(chapter, 0), chapter) for chapter in chapters_touched]
            orders = [item for item in orders if item[0] > 0]
            if not orders:
                continue
            folded.entity_spans[entity_id] = (min(orders)[1], max(orders)[1])
        return folded

    def _latest_entity_states(
        self, folded: _FoldedGraph, boundary: ChapterBoundary
    ) -> dict[str, tuple[int, _EntityStateBucket]]:
        latest: dict[str, tuple[int, _EntityStateBucket]] = {}
        for (chapter_id, entity_id), bucket in folded.entity_states.items():
            order = folded.order_map.get(chapter_id, 0)
            if order == 0 or order > boundary.chapter_order:
                continue
            current = latest.get(entity_id)
            if current is None or folded.order_map.get(current[0], 0) < order:
                latest[entity_id] = (chapter_id, bucket)
        return latest

    def fetch_entity_snapshots(self, boundary: ChapterBoundary) -> list[EntitySnapshotRow]:
        "用于选择目标章节以前最近状态并继承无变化实体"
        folded = self._fold_graph(boundary.run_id)
        entities = {
            str(row.entity_id): row
            for row in self.session.execute(select(GraphEntity).where(GraphEntity.run_id == boundary.run_id)).scalars()
        }
        latest = self._latest_entity_states(folded, boundary)
        result: list[EntitySnapshotRow] = []
        for entity_id in sorted(entities):
            span = folded.entity_spans.get(entity_id)
            if span is None:
                continue
            first_order = folded.order_map.get(span[0], 0)
            if first_order == 0 or first_order > boundary.chapter_order:
                continue
            entity = entities[entity_id]
            state = latest.get(entity_id)
            result.append(
                EntitySnapshotRow(
                    entity_id=entity_id,
                    name=str(entity.canonical_name),
                    entity_type=str(entity.entity_type),
                    tags=list(state[1].state.get("tags", [])) if state else [],
                    attributes=dict(state[1].state.get("attributes", {})) if state else {},
                    first_seen_chapter=span[0],
                    last_seen_chapter=span[1],
                    state_chapter_id=state[0] if state else None,
                    state=dict(state[1].state) if state else {},
                )
            )
        return result

    def _latest_relation_states(
        self, folded: _FoldedGraph, boundary: ChapterBoundary
    ) -> dict[str, tuple[int, _RelationStateBucket]]:
        latest: dict[str, tuple[int, _RelationStateBucket]] = {}
        for (chapter_id, relation_id), bucket in folded.relation_states.items():
            order = folded.order_map.get(chapter_id, 0)
            if order == 0 or order > boundary.chapter_order:
                continue
            current = latest.get(relation_id)
            if current is None or folded.order_map.get(current[0], 0) < order:
                latest[relation_id] = (chapter_id, bucket)
        return latest

    def fetch_relation_snapshots(
        self, boundary: ChapterBoundary, *, active_only: bool = True
    ) -> list[RelationSnapshotRow]:
        "用于选择目标章节以前最近关系状态并过滤活动状态"
        folded = self._fold_graph(boundary.run_id)
        entity_names = {
            str(row.entity_id): str(row.canonical_name)
            for row in self.session.execute(select(GraphEntity).where(GraphEntity.run_id == boundary.run_id)).scalars()
        }
        relations = {str(row.relation_id): row for row in self.session.execute(select(GraphRelation)).scalars()}
        result: list[RelationSnapshotRow] = []
        for relation_id, (chapter_id, bucket) in self._latest_relation_states(folded, boundary).items():
            if active_only and not bucket.is_active:
                continue
            relation = relations.get(relation_id)
            if relation is None:
                continue

            span = folded.relation_spans.get(relation_id, (chapter_id, chapter_id))
            result.append(
                RelationSnapshotRow(
                    chapter_id=chapter_id,
                    relation_id=relation_id,
                    from_entity_id=str(relation.from_entity_id),
                    to_entity_id=str(relation.to_entity_id),
                    from_name=entity_names.get(str(relation.from_entity_id), str(relation.from_entity_id)),
                    to_name=entity_names.get(str(relation.to_entity_id), str(relation.to_entity_id)),
                    relation_type=str(relation.relation_type),
                    directionality=None,
                    relation_semantics=None,
                    attributes=dict(bucket.attributes),
                    is_active=bool(bucket.is_active),
                    changes=[
                        _display_relation_change(
                            change,
                            from_name=entity_names.get(str(relation.from_entity_id)),
                            to_name=entity_names.get(str(relation.to_entity_id)),
                        )
                        for change in bucket.changes
                    ],
                    first_seen_chapter=span[0],
                    last_seen_chapter=span[1],
                )
            )
        return result

    def fetch_snapshot(self, run_id: str, *, chapter_id: int | None = None) -> GraphSnapshotRow | None:
        "用于返回目标章节边界的实体状态与有效关系"
        boundary = self.resolve_chapter_boundary(run_id, chapter_id=chapter_id)
        if boundary is None:
            return None
        return GraphSnapshotRow(
            chapter_boundary=boundary,
            entities=self.fetch_entity_snapshots(boundary),
            relations=self.fetch_relation_snapshots(boundary, active_only=True),
        )

    def fetch_changes(
        self,
        run_id: str,
        *,
        chapter_id: int | None = None,
        offset: int = 0,
        limit: int | None = 200,
    ) -> tuple[list[GraphChangeRow], int]:
        "用于按章节倒序分页返回状态和关系变化"
        if offset < 0:
            raise ValueError("graph changes offset 不能小于 0")
        boundary = self.resolve_chapter_boundary(run_id, chapter_id=chapter_id)
        if boundary is None:
            return [], 0
        folded = self._fold_graph(run_id)
        entities = {
            str(row.entity_id): row
            for row in self.session.execute(select(GraphEntity).where(GraphEntity.run_id == run_id)).scalars()
        }
        relations = {str(row.relation_id): row for row in self.session.execute(select(GraphRelation)).scalars()}
        entity_names = {key: str(row.canonical_name) for key, row in entities.items()}
        changes: list[GraphChangeRow] = []
        for (state_chapter, entity_id), bucket in folded.entity_states.items():
            state_order = folded.order_map.get(state_chapter, 0)
            if state_order == 0 or state_order > boundary.chapter_order:
                continue
            if chapter_id is not None and state_chapter != chapter_id:
                continue
            entity = entities.get(entity_id)
            if entity is None:
                continue
            for index, change in enumerate(bucket.changes):
                fact_id = str(change.get("fact_id", ""))
                changes.append(
                    GraphChangeRow(
                        change_id=f"state:{run_id}:{state_chapter}:{entity_id}:{fact_id}:{index}",
                        change_kind="state",
                        chapter_id=int(change.get("chapter_id") or state_chapter),
                        chapter_order=state_order,
                        fact_id=fact_id,
                        effective_chapter_id=int(change.get("chapter_id") or state_chapter),
                        confidence="high",
                        changes=[dict(change)],
                        entity_id=entity_id,
                        entity_name=str(entity.canonical_name),
                        entity_type=str(entity.entity_type),
                    )
                )
        for (state_chapter, relation_id), relation_bucket in folded.relation_states.items():
            state_order = folded.order_map.get(state_chapter, 0)
            if state_order == 0 or state_order > boundary.chapter_order:
                continue
            if chapter_id is not None and state_chapter != chapter_id:
                continue
            relation = relations.get(relation_id)
            if relation is None:
                continue

            for index, change in enumerate(relation_bucket.changes):
                fact_id = str(change.get("fact_id", ""))
                changes.append(
                    GraphChangeRow(
                        change_id=f"relation:{run_id}:{state_chapter}:{relation_id}:{fact_id}:{index}",
                        change_kind="relation",
                        chapter_id=int(change.get("chapter_id") or state_chapter),
                        chapter_order=state_order,
                        fact_id=fact_id,
                        effective_chapter_id=int(change.get("chapter_id") or state_chapter),
                        confidence="high",
                        changes=[
                            _display_relation_change(
                                change,
                                from_name=entity_names.get(str(relation.from_entity_id)),
                                to_name=entity_names.get(str(relation.to_entity_id)),
                            )
                        ],
                        relation_id=relation_id,
                        from_entity_id=str(relation.from_entity_id),
                        to_entity_id=str(relation.to_entity_id),
                        from_name=entity_names.get(str(relation.from_entity_id)),
                        to_name=entity_names.get(str(relation.to_entity_id)),
                        relation_type=str(relation.relation_type),
                        directionality=None,
                        relation_semantics=None,
                    )
                )
        changes.sort(key=lambda row: (row.chapter_order, row.change_kind, row.change_id), reverse=True)
        total = len(changes)
        end = None if limit is None else offset + max(1, min(limit, 200))
        return changes[offset:end], total

    def fetch_latest_entity_rows(self, run_id: str, *, entity_type: str | None = None) -> list[EntitySnapshotRow]:
        "用于读取当前章节边界的实体状态"
        boundary = self.resolve_persisted_boundary(run_id)
        if boundary is None:
            return []
        return [
            row
            for row in self.fetch_entity_snapshots(boundary)
            if (entity_type is None or row.entity_type == entity_type)
        ]

    def fetch_latest_relations(self, run_id: str, *, active_only: bool = True) -> list[RelationSnapshotRow]:
        "用于读取当前章节边界的关系状态"
        boundary = self.resolve_persisted_boundary(run_id)
        return [] if boundary is None else self.fetch_relation_snapshots(boundary, active_only=active_only)

    def fetch_relation_history(self, run_id: str) -> list[RelationSnapshotRow]:
        "按章节顺序读取关系历史，共享一次折叠结果，避免逐状态重建全图"
        folded = self._fold_graph(run_id)
        entity_names = {
            str(row.entity_id): str(row.canonical_name)
            for row in self.session.execute(select(GraphEntity).where(GraphEntity.run_id == run_id)).scalars()
        }
        relations = {str(row.relation_id): row for row in self.session.execute(select(GraphRelation)).scalars()}
        rows: list[RelationSnapshotRow] = []
        for (chapter_id, relation_id), bucket in sorted(
            folded.relation_states.items(), key=lambda item: folded.order_map.get(item[0][0], 0)
        ):
            relation = relations.get(relation_id)
            if relation is None:
                continue

            span = folded.relation_spans.get(relation_id, (chapter_id, chapter_id))
            rows.append(
                RelationSnapshotRow(
                    chapter_id=chapter_id,
                    relation_id=relation_id,
                    from_entity_id=str(relation.from_entity_id),
                    to_entity_id=str(relation.to_entity_id),
                    from_name=entity_names.get(str(relation.from_entity_id), str(relation.from_entity_id)),
                    to_name=entity_names.get(str(relation.to_entity_id), str(relation.to_entity_id)),
                    relation_type=str(relation.relation_type),
                    directionality=None,
                    relation_semantics=None,
                    attributes=dict(bucket.attributes),
                    is_active=bool(bucket.is_active),
                    changes=[
                        _display_relation_change(
                            change,
                            from_name=entity_names.get(str(relation.from_entity_id)),
                            to_name=entity_names.get(str(relation.to_entity_id)),
                        )
                        for change in bucket.changes
                    ],
                    first_seen_chapter=span[0],
                    last_seen_chapter=span[1],
                )
            )
        return rows

    def fetch_relation_changes(self, run_id: str, *, limit: int | None = None) -> list[GraphChangeRow]:
        "用于读取诊断时间轴所需的关系变化事实"
        rows, _total = self.fetch_changes(run_id, limit=None)
        relation_rows = [row for row in rows if row.change_kind == "relation"]
        return relation_rows if limit is None else relation_rows[:limit]

    def count_chapters(self, run_id: str) -> int:
        "用于统计当前运行已提交的章节数量"
        return len(self._chapter_rows(run_id))


@dataclass(slots=True)
class _EntityStateBucket:
    "一次 (章, 实体) 的折叠结果：该点状态与本章贡献的变化条目"

    state: dict[str, Any] = field(default_factory=dict)
    changes: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class _RelationStateBucket:
    "一次 (章, 关系) 的折叠结果：活动/支持度/身份判断与本章变化条目"

    relation_type: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    is_active: bool = True
    changes: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class _FoldedGraph:
    "run 内一次折叠的全部读侧投影"

    order_map: dict[int, int] = field(default_factory=dict)
    entity_states: dict[tuple[int, str], _EntityStateBucket] = field(default_factory=dict)
    relation_states: dict[tuple[int, str], _RelationStateBucket] = field(default_factory=dict)
    entity_spans: dict[str, tuple[int, int]] = field(default_factory=dict)
    relation_spans: dict[str, tuple[int, int]] = field(default_factory=dict)
