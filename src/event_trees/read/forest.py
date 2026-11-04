"章节边界内的原事件节点与原事件关系投影"

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from src.event_trees.action_order import action_order
from src.event_trees.read.models import (
    EventEdgeRow,
    EventForestSnapshot,
    EventNodeRow,
    EventTreeRow,
    ForeshadowingEdgeRow,
)
from src.event_trees.read.organization import EventTreeQuery
from src.storage import Storage
from src.storage.records.graph import ChapterBoundary

if TYPE_CHECKING:
    pass

    from src.storage.records.models import ChapterRecord as Chapter


class EventForestQuery:
    "章节节点使用自身事件身份，完整事件仅作为全书归属"

    def __init__(self, session: Storage) -> None:
        self.session = session
        self.records = session.forest

    def _chapter_rows(self, run_id: str) -> list[Chapter]:
        return self.records.fetch_chapters(run_id)

    def resolve_chapter_boundary(
        self,
        run_id: str,
        *,
        chapter_id: int | None = None,
        chapters: list[Chapter] | None = None,
    ) -> ChapterBoundary | None:
        chapters = self._chapter_rows(run_id) if chapters is None else chapters
        outputs = {row.chapter_id: row for row in self.records.fetch_saved_outputs(run_id)}
        target = (
            next((row for row in reversed(chapters) if row.chapter_id in outputs), None)
            if chapter_id is None
            else next((row for row in chapters if row.chapter_id == chapter_id), None)
        )
        if target is None or target.chapter_id not in outputs:
            return None
        return ChapterBoundary(
            run_id=run_id,
            chapter_id=target.chapter_id,
            chapter_order=int(target.sequence),
            first_chapter_id=target.chapter_id,
            last_chapter_id=target.chapter_id,
            annotation_id=outputs[target.chapter_id].output_id,
        )

    def fetch_event_nodes(self, run_id: str, *, max_chapter_order: int) -> list[EventNodeRow]:
        "章级投影只纳入已到阅读边界的单章事件与父子关系"
        query = EventTreeQuery(self.session, run_id)
        query.fetch()
        return self._event_nodes(query, max_chapter_order=max_chapter_order)

    def _event_nodes(self, query: EventTreeQuery, *, max_chapter_order: int) -> list[EventNodeRow]:
        sources = {
            event.event_id: event
            for event in query.events.values()
            if event.annotation_record_id is not None
            and event.chapter_id is not None
            and event.chapter_order is not None
            and event.chapter_order <= max_chapter_order
            and event.from_chapter_id == event.chapter_id
            and event.to_chapter_id == event.chapter_id
        }
        visible_members: set[str] = set()
        visible_references: set[tuple[str, str]] = set()
        for row, refs in zip(query._structure_links, query._structure_evidence_payloads(), strict=True):
            if not all(query.orders[ref["chapter_id"]] <= max_chapter_order for ref in refs):
                continue
            if row.member_event_id is not None:
                visible_members.add(row.member_event_id)
            elif row.parent_tree_id is not None and row.child_tree_id is not None:
                visible_references.add((row.parent_tree_id, row.child_tree_id))
        parents = {
            key: [
                parent
                for parent in query.graph.event_parents(key)
                if parent in sources
                and sources[key].chapter_id == sources[parent].chapter_id
                and key in visible_members
                and parent in visible_members
                and (
                    query.graph.event_tree[key] == query.graph.event_tree[parent]
                    or (query.graph.event_tree[parent], query.graph.event_tree[key]) in visible_references
                )
            ]
            for key in sources
        }
        result = []
        for ordinal, event in enumerate(
            sorted(sources.values(), key=lambda item: (item.chapter_order or 0, item.char_start, item.event_id))
        ):
            if any(ref["chapter_id"] != event.chapter_id for ref in event.evidence):
                raise ValueError("章级事件证据与自身章节不一致")
            result.append(
                EventNodeRow(
                    event_id=event.event_id,
                    chapter_id=cast(int, event.chapter_id),
                    chapter_order=cast(int, event.chapter_order),
                    from_chapter_id=event.from_chapter_id,
                    to_chapter_id=event.to_chapter_id,
                    description=event.summary,
                    participants=[dict(item, entity=dict(item["entity"])) for item in event.participants],
                    anchor_paragraph_ids=sorted({ref["paragraph_id"] for ref in event.evidence}),
                    char_start=event.char_start,
                    char_end=event.char_end,
                    evidence=list(event.evidence),
                    causal_event_refs=[],
                    tree_id=query.graph.event_tree[event.event_id],
                    cause_role="root" if not parents[event.event_id] else "main",
                    parent_event_ids=parents[event.event_id],
                    evidence_scope="paragraph",
                    payload_path=event.payload_path,
                    event_ordinal=ordinal,
                )
            )
        return result

    def fetch_snapshot(self, run_id: str, *, chapter_id: int | None = None) -> EventForestSnapshot | None:
        "读取指定章节边界内的节点与原事件关系"
        boundary = self.resolve_chapter_boundary(run_id, chapter_id=chapter_id)
        if boundary is None:
            return None
        query = EventTreeQuery(self.session, run_id)
        query.fetch()
        nodes = self._event_nodes(query, max_chapter_order=boundary.chapter_order)
        by_id = {row.event_id: row for row in nodes}
        visible_relations = [
            row
            for row in query.relations
            if row.source_kind == "event"
            and row.target_kind == "event"
            and row.source_id in by_id
            and row.target_id in by_id
            and all(query.orders[item["chapter_id"]] <= boundary.chapter_order for item in row.evidence)
        ]
        edges = [
            EventEdgeRow(
                edge_id=row.relation_id,
                edge_type="causal",
                source_event_id=row.source_id,
                target_event_id=row.target_id,
                source_chapter_id=by_id[row.source_id].chapter_id,
                target_chapter_id=by_id[row.target_id].chapter_id,
                is_active=True,
                evidence=list(row.evidence),
            )
            for row in visible_relations
            if row.relation_type == "causal"
        ]
        by_source: dict[str, list[Any]] = {}
        for action in sorted(query.actions, key=action_order):
            if (
                action.chapter_order is not None
                and action.chapter_order <= boundary.chapter_order
                and action.source_event_id in by_id
            ):
                by_source.setdefault(action.source_event_id, []).append(action)
        threads = []
        for source_id, actions in by_source.items():
            latest = actions[-1]
            entries = [query._action_entry(action) for action in actions]
            payoff = (
                latest.target_event_id if latest.action_type == "payoff" and latest.target_event_id in by_id else None
            )
            status = {"setup": "open", "reinforce": "reinforced", "payoff": "likely_paid_off"}[latest.action_type]
            threads.append(
                ForeshadowingEdgeRow(
                    source_event_id=source_id,
                    run_id=run_id,
                    source_locator=entries[0]["source_locator"],
                    target_event_id=latest.target_event_id,
                    target_locator=entries[-1]["target_locator"],
                    actions=entries,
                    payoff_event_id=payoff,
                    first_chapter_id=actions[0].chapter_id,
                    last_chapter_id=latest.chapter_id,
                    description=by_id[source_id].description,
                    status=status,
                    active=status != "likely_paid_off",
                )
            )
        grouped: dict[str, list[EventNodeRow]] = {}
        for node in nodes:
            grouped.setdefault(node.tree_id, []).append(node)
        return EventForestSnapshot(
            chapter_id=boundary.chapter_id,
            chapter_order=boundary.chapter_order,
            visible_through_chapter_order=boundary.chapter_order,
            derived_event_order=[row.event_id for row in nodes],
            event_nodes=nodes,
            event_trees=[
                EventTreeRow(
                    tree_id=tree_id,
                    entry_event_id=members[0].event_id,
                    main_chain=[node.event_id for node in members],
                    secondary_groups=[],
                    chapter_ids=sorted({node.chapter_id for node in members}),
                    char_start=min(node.char_start for node in members),
                    char_end=max(node.char_end for node in members),
                )
                for tree_id, members in grouped.items()
            ],
            causal_edges=edges,
            foreshadowing_edges=threads,
        )
