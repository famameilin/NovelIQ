"章节边界内的原声明节点与原声明关系投影"

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
    "章节节点使用自身声明身份，完整事件仅作为全书归属"

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
        "读取章节边界内的原声明，不用全书正文覆盖章级正文"
        query = EventTreeQuery(self.session, run_id)
        query.fetch()
        chapter_id = next(
            (row["chapter_id"] for row in query.chapters if row["chapter_order"] == max_chapter_order), None
        )
        boundary = self.resolve_chapter_boundary(run_id, chapter_id=chapter_id) if chapter_id is not None else None
        projection = EntityReferenceProjection.load(self.session, run_id, boundary=boundary)
        nodes: list[EventNodeRow] = []
        for source in query.declarations.values():
            if source.chapter_order is None or source.chapter_order > max_chapter_order:
                continue
            binding = query.bindings.get(source.declaration_id)
            evidence = list(source.evidence)
            if source.chapter_id is None or any(item["chapter_id"] != source.chapter_id for item in evidence):
                raise ValueError("章级声明证据与自身章节不一致")
            positions = [item["char_start"] for item in evidence if item.get("char_start") is not None]
            ends = [item["char_end"] for item in evidence if item.get("char_end") is not None]
            nodes.append(
                EventNodeRow(
                    declaration_id=source.declaration_id,
                    event_id=binding.event_id if binding else None,
                    chapter_id=source.chapter_id,
                    chapter_order=source.chapter_order,
                    description=source.summary,
                    participants=projection.participants(source.participants),
                    anchor_paragraph_ids=sorted(
                        {item["paragraph_id"] for item in evidence if item.get("paragraph_id") is not None}
                    ),
                    char_start=min(positions, default=source.char_start),
                    char_end=max(ends, default=source.char_end),
                    evidence=evidence,
                    causal_event_refs=[],
                    tree_id=source.declaration_id,
                    cause_role="root",
                    parent_event_id=None,
                    evidence_scope="paragraph"
                    if all(item.get("paragraph_id") is not None for item in evidence)
                    else "chapter",
                    payload_path=source.payload_path,
                    event_ordinal=0,
                )
            )
        nodes.sort(key=lambda row: (row.chapter_order, row.char_start, row.declaration_id))
        return nodes

    def fetch_snapshot(self, run_id: str, *, chapter_id: int | None = None) -> EventForestSnapshot | None:
        "读取指定章节边界内的节点与原声明关系"
        boundary = self.resolve_chapter_boundary(run_id, chapter_id=chapter_id)
        if boundary is None:
            return None
        nodes = self.fetch_event_nodes(run_id, max_chapter_order=boundary.chapter_order)
        by_id = {row.declaration_id: row for row in nodes}
        query = EventTreeQuery(self.session, run_id)
        query.fetch()
        visible_relations = [
            row
            for row in query.declaration_relations
            if row.source_kind == "declaration"
            and row.target_kind == "declaration"
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
                and action.source_declaration_id in by_id
            ):
                by_root.setdefault(action.source_declaration_id, []).append(action)
        threads = []
        for root_id, actions in by_root.items():
            latest = actions[-1]
            payoff = (
                latest.target_declaration_id
                if latest.action_type == "payoff" and latest.target_declaration_id in by_id
                else None
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
            derived_event_order=[row.declaration_id for row in nodes],
            event_nodes=nodes,
            event_trees=[
                EventTreeRow(
                    tree_id=row.declaration_id,
                    root_event_id=row.declaration_id,
                    main_chain=[row.declaration_id],
                    secondary_groups=[],
                    chapter_ids=[row.chapter_id],
                    char_start=row.char_start,
                    char_end=row.char_end,
                )
                for row in nodes
            ],
            causal_edges=edges,
            foreshadowing_edges=threads,
        )
