"章节边界内的原事件节点与原事件关系投影"

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from src.event_trees.action_order import action_order, load_foreshadowing_actions
from src.event_trees.read.models import (
    EventEdgeRow,
    EventForestSnapshot,
    EventNodeRow,
    EventTreeRow,
    ForeshadowingEdgeRow,
)
from src.event_trees.read.organization import EventTreeQuery
from src.fact_graph.read.references import EntityReferenceProjection
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
        """章级投影只纳入本章标注的单章事件与章内包含边"""
        query = EventTreeQuery(self.session, run_id)
        query.fetch()
        chapter_id = next(
            (row["chapter_id"] for row in query.chapters if row["chapter_order"] == max_chapter_order), None
        )
        boundary = self.resolve_chapter_boundary(run_id, chapter_id=chapter_id) if chapter_id is not None else None
        projection = EntityReferenceProjection.load(self.session, run_id, boundary=boundary)
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
        parents = {
            child: link.contained_parent_id
            for child, link in query.parent_of.items()
            if child in sources
            and link.contained_parent_id in sources
            and sources[child].chapter_id == sources[link.contained_parent_id].chapter_id
        }

        def root_of(identifier: str) -> str:
            while identifier in parents:
                identifier = parents[identifier]
            return identifier

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
                    participants=projection.participants(event.participants),
                    anchor_paragraph_ids=sorted({ref["paragraph_id"] for ref in event.evidence}),
                    char_start=event.char_start,
                    char_end=event.char_end,
                    evidence=list(event.evidence),
                    causal_event_refs=[],
                    tree_id=root_of(event.event_id),
                    cause_role="root" if event.event_id not in parents else "main",
                    parent_event_id=parents.get(event.event_id),
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
        nodes = self.fetch_event_nodes(run_id, max_chapter_order=boundary.chapter_order)
        by_id = {row.event_id: row for row in nodes}
        query = EventTreeQuery(self.session, run_id)
        query.fetch()
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
        by_root: dict[str, list[Any]] = {}
        for action in sorted(load_foreshadowing_actions(self.session, run_id), key=action_order):
            if (
                action.chapter_order is not None
                and action.chapter_order <= boundary.chapter_order
                and action.source_event_id in by_id
            ):
                by_root.setdefault(action.source_event_id, []).append(action)
        threads = []
        for root_id, actions in by_root.items():
            latest = actions[-1]
            payoff = (
                latest.target_event_id if latest.action_type == "payoff" and latest.target_event_id in by_id else None
            )
            status = {"setup": "open", "reinforce": "reinforced", "payoff": "likely_paid_off"}[latest.action_type]
            threads.append(
                ForeshadowingEdgeRow(
                    root_event_id=root_id,
                    run_id=run_id,
                    tree_id=root_id,
                    payoff_event_id=payoff,
                    first_chapter_id=actions[0].chapter_id,
                    last_chapter_id=latest.chapter_id,
                    description=by_id[root_id].description,
                    status=status,
                    active=status != "likely_paid_off",
                )
            )
        return EventForestSnapshot(
            chapter_id=boundary.chapter_id,
            chapter_order=boundary.chapter_order,
            visible_through_chapter_order=boundary.chapter_order,
            derived_event_order=[row.event_id for row in nodes],
            event_nodes=nodes,
            event_trees=[
                EventTreeRow(
                    tree_id=root,
                    root_event_id=root,
                    main_chain=[root],
                    secondary_groups=[],
                    chapter_ids=sorted({node.chapter_id for node in nodes if node.tree_id == root}),
                    char_start=min(node.char_start for node in nodes if node.tree_id == root),
                    char_end=max(node.char_end for node in nodes if node.tree_id == root),
                )
                for root in dict.fromkeys(node.tree_id for node in nodes)
            ],
            causal_edges=edges,
            foreshadowing_edges=threads,
        )
