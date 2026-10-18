"""章节截点内的正式事件阶段投影，不把章级声明当作第二种事件

2026-10-16 全库 3NF 改造（35 表冻结结构）：阅读截点由 chapters 与已保存
chapter_annotations 决定；事件阶段取 event_revisions 的显式链；因果/伏笔
边取 narrative_links 的语义形状；伏笔动作取 event_foreshadowing_actions。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.event_trees.action_order import action_order
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
    """保留章节阅读截点，节点始终使用已发布的正式 event_id"""

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
            chapter_order=chapters.index(target) + 1,
            first_chapter_id=target.chapter_id,
            last_chapter_id=target.chapter_id,
            annotation_id=outputs[target.chapter_id].output_id,
        )

    def fetch_event_nodes(self, run_id: str, *, max_chapter_order: int) -> list[EventNodeRow]:
        """阶段沿已确认链裁剪，不能把后章最终概要泄漏给前章阅读截点"""
        query = EventTreeQuery(self.session, run_id)
        query.fetch()
        chapter_id = next(
            (row["chapter_id"] for row in query.chapters if row["chapter_order"] == max_chapter_order), None
        )
        boundary = self.resolve_chapter_boundary(run_id, chapter_id=chapter_id) if chapter_id is not None else None
        projection = EntityReferenceProjection.load(self.session, run_id, boundary=boundary)
        nodes: list[EventNodeRow] = []
        for event in query.events.values():
            visible = [
                stage
                for stage in query._stages(event)
                if stage.evidence
                and all(query.orders[item["chapter_id"]] <= max_chapter_order for item in stage.evidence)
            ]
            if not visible:
                continue
            stage = visible[-1]
            evidence: list[dict[str, Any]] = list(stage.evidence)
            chapter_id = min((item["chapter_id"] for item in evidence), key=query.orders.__getitem__)
            positions = [item["char_start"] for item in evidence if item.get("char_start") is not None]
            ends = [item["char_end"] for item in evidence if item.get("char_end") is not None]
            # 历史 DTO 承载每个正式事件本身，包含和因果不能由 main/secondary 捏造
            nodes.append(
                EventNodeRow(
                    event_id=event.event_id,
                    chapter_id=chapter_id,
                    chapter_order=query.orders[chapter_id],
                    description=stage.summary,
                    participants=projection.participants(stage.participants),
                    anchor_paragraph_ids=sorted(
                        {item["paragraph_id"] for item in evidence if item.get("paragraph_id") is not None}
                    ),
                    char_start=min(positions, default=event.first_text_position or 0),
                    char_end=max(ends, default=event.first_text_position or 0),
                    evidence=evidence,
                    causal_event_refs=[],
                    tree_id=event.event_id,
                    cause_role="root",
                    parent_event_id=None,
                    evidence_scope="paragraph"
                    if all(item.get("paragraph_id") is not None for item in evidence)
                    else "chapter",
                    payload_path=f"event_revisions/{stage.revision_id}",
                    event_ordinal=0,
                )
            )
        nodes.sort(key=lambda row: (row.chapter_order, row.char_start, row.event_id))
        return nodes

    def fetch_snapshot(self, run_id: str, *, chapter_id: int | None = None) -> EventForestSnapshot | None:
        """正式事件、因果和伏笔都直接使用事件身份，不在读取时绑定声明"""
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
            if row.source_id in by_id
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
        for action in sorted(query.actions, key=action_order):
            if (
                action.chapter_order is not None
                and action.chapter_order <= boundary.chapter_order
                and action.root_event_id in by_id
            ):
                by_root.setdefault(action.root_event_id, []).append(action)
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
                    tree_id=row.event_id,
                    root_event_id=row.event_id,
                    main_chain=[row.event_id],
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
