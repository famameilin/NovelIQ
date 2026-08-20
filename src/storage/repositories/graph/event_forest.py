"""章节事件森林查询 Repository"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.models import Chapter, ChapterAnnotationRecord, EventEdge, EventNode, ForeshadowingThread
from src.storage.models.graph import ChapterBoundary


@dataclass(frozen=True)
class EventNodeRow:
    """2026-08-19 用于返回章节事件节点"""

    event_id: str
    chapter_id: int
    chapter_order: int
    description: str
    participants: list[dict[str, Any]]
    anchor_paragraph_ids: list[int]
    char_start: int
    char_end: int
    text_hash: str
    evidence: list[dict[str, Any]]
    causal_event_refs: list[str]
    tree_id: str
    cause_role: str


@dataclass(frozen=True)
class EventEdgeRow:
    """2026-08-19 用于返回章节事件因果边"""

    edge_id: str
    edge_type: str
    source_event_id: str
    target_event_id: str
    source_chapter_id: int
    target_chapter_id: int
    is_active: bool
    evidence: list[dict[str, Any]]


@dataclass(frozen=True)
class ForeshadowingEdgeRow:
    """2026-08-19 用于返回章节伏笔边"""

    setup_id: str
    run_id: str
    setup_event_id: str
    payoff_event_id: str | None
    first_chapter_id: int
    last_chapter_id: int
    setup_summary: str
    status: str
    active: bool


@dataclass(frozen=True)
class EventSecondaryGroupRow:
    """2026-08-19 用于返回事件树的次因分支"""

    target_event_id: str
    branch: list[str]


@dataclass(frozen=True)
class EventTreeRow:
    """2026-08-19 用于返回一棵事件树"""

    tree_id: str
    root_event_id: str
    main_chain: list[str]
    secondary_groups: list[EventSecondaryGroupRow]
    chapter_ids: list[int]
    char_start: int
    char_end: int


@dataclass(frozen=True)
class EventForestSnapshot:
    """2026-08-19 用于返回章节边界内的事件森林"""

    chapter_id: int
    chapter_order: int
    visible_through_chapter_order: int
    derived_event_order: list[str]
    event_nodes: list[EventNodeRow]
    event_trees: list[EventTreeRow]
    causal_edges: list[EventEdgeRow]
    foreshadowing_edges: list[ForeshadowingEdgeRow]


class EventForestRepository:
    """2026-08-19 用于查询章节事件森林"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def _chapter_rows(self, run_id: str) -> list[Chapter]:
        """2026-08-19 用于按章节身份读取有正文章节并确定排序"""
        return list(
            self.session.execute(
                select(Chapter)
                .where(Chapter.run_id == run_id, Chapter.text.isnot(None))
                .order_by(Chapter.sequence, Chapter.chapter_id)
            ).scalars()
        )

    def _chapter_ids_for_order(self, run_id: str, max_chapter_order: int) -> set[int]:
        """2026-08-19 用于按 chapter_order 解析可见章节集合"""
        return {
            int(chapter.chapter_id)
            for index, chapter in enumerate(self._chapter_rows(run_id), start=1)
            if index <= max_chapter_order
        }

    def resolve_chapter_boundary(
        self,
        run_id: str,
        *,
        chapter_id: int | None = None,
    ) -> ChapterBoundary | None:
        """2026-08-19 用于按章节身份解析当前运行的图谱边界"""
        chapters = self._chapter_rows(run_id)
        if chapter_id is None:
            target = chapters[-1] if chapters else None
        else:
            target = next((chapter for chapter in chapters if int(chapter.chapter_id) == chapter_id), None)
        if target is None:
            return None
        annotation = self.session.execute(
            select(ChapterAnnotationRecord).where(
                ChapterAnnotationRecord.run_id == run_id,
                ChapterAnnotationRecord.chapter_id == target.chapter_id,
            )
        ).scalar_one_or_none()
        if annotation is None:
            return None
        order = chapters.index(target) + 1
        return ChapterBoundary(
            run_id=run_id,
            chapter_id=int(target.chapter_id),
            chapter_order=order,
            first_chapter_id=int(target.chapter_id),
            last_chapter_id=int(target.chapter_id),
            annotation_id=str(annotation.annotation_id),
        )

    def fetch_event_nodes(self, run_id: str, *, max_chapter_order: int) -> list[EventNodeRow]:
        """2026-08-19 用于读取截止章节边界的事件节点"""
        rows = self.session.execute(
            select(EventNode)
            .where(EventNode.run_id == run_id, EventNode.chapter_order <= max_chapter_order)
            .order_by(EventNode.chapter_order, EventNode.event_id)
        ).scalars()
        return [
            EventNodeRow(
                event_id=node.event_id,
                chapter_id=node.chapter_id,
                chapter_order=node.chapter_order,
                description=node.description,
                participants=list(node.participants),
                anchor_paragraph_ids=list(node.anchor_paragraph_ids),
                char_start=node.char_start,
                char_end=node.char_end,
                text_hash=node.text_hash,
                evidence=list(node.evidence),
                causal_event_refs=list(node.causal_event_refs),
                tree_id=node.tree_id,
                cause_role=node.cause_role,
            )
            for node in rows
        ]

    def fetch_event_edges(self, run_id: str, *, max_chapter_order: int) -> list[EventEdgeRow]:
        """2026-08-19 用于读取截止章节边界的活跃因果边"""
        chapter_ids = self._chapter_ids_for_order(run_id, max_chapter_order)
        if not chapter_ids:
            return []
        rows = self.session.execute(
            select(EventEdge)
            .where(
                EventEdge.run_id == run_id,
                EventEdge.is_active.is_(True),
                EventEdge.source_chapter_id.in_(chapter_ids),
                EventEdge.target_chapter_id.in_(chapter_ids),
            )
            .order_by(EventEdge.edge_id)
        ).scalars()
        return [
            EventEdgeRow(
                edge_id=edge.edge_id,
                edge_type=edge.edge_type,
                source_event_id=edge.source_event_id,
                target_event_id=edge.target_event_id,
                source_chapter_id=edge.source_chapter_id,
                target_chapter_id=edge.target_chapter_id,
                is_active=bool(edge.is_active),
                evidence=list(edge.evidence),
            )
            for edge in rows
        ]

    def fetch_foreshadowing_edges(self, run_id: str, *, max_chapter_order: int) -> list[ForeshadowingEdgeRow]:
        """2026-08-19 用于读取截止章节边界的伏笔边"""
        chapter_ids = self._chapter_ids_for_order(run_id, max_chapter_order)
        if not chapter_ids:
            return []
        rows = self.session.execute(
            select(ForeshadowingThread)
            .join(
                Chapter,
                (Chapter.run_id == ForeshadowingThread.run_id)
                & (Chapter.chapter_id == ForeshadowingThread.first_chapter_id),
            )
            .where(ForeshadowingThread.run_id == run_id, ForeshadowingThread.first_chapter_id.in_(chapter_ids))
            .order_by(Chapter.sequence, ForeshadowingThread.first_chapter_id, ForeshadowingThread.setup_id)
        ).scalars()
        return [
            ForeshadowingEdgeRow(
                setup_id=thread.setup_id,
                run_id=thread.run_id,
                setup_event_id=thread.setup_event_id,
                payoff_event_id=thread.payoff_event_id,
                first_chapter_id=thread.first_chapter_id,
                last_chapter_id=thread.last_chapter_id,
                setup_summary=thread.setup_summary,
                status=thread.status,
                active=thread.active,
            )
            for thread in rows
        ]

    def _build_event_trees(self, event_nodes: list[EventNodeRow]) -> list[EventTreeRow]:
        """2026-08-19 用于按 tree_id 组装事件树视图"""
        nodes_by_tree: dict[str, list[EventNodeRow]] = {}
        for node in event_nodes:
            nodes_by_tree.setdefault(node.tree_id, []).append(node)

        def sort_key(node: EventNodeRow) -> tuple[int, int, int, str]:
            return (node.chapter_order, node.char_start, node.char_end, node.event_id)

        trees: list[tuple[EventTreeRow, tuple[int, int, int, str]]] = []
        for tree_id, nodes in nodes_by_tree.items():
            ordered = sorted(nodes, key=sort_key)
            roots = [node for node in ordered if node.cause_role == "root"]
            root_id = roots[0].event_id if len(roots) == 1 else ordered[0].event_id
            secondary_by_target: dict[str, list[str]] = {}
            for node in ordered:
                if node.cause_role != "secondary":
                    continue
                target = node.causal_event_refs[0] if node.causal_event_refs else tree_id
                secondary_by_target.setdefault(target, []).append(node.event_id)
            trees.append(
                (
                    EventTreeRow(
                        tree_id=tree_id,
                        root_event_id=root_id,
                        main_chain=[node.event_id for node in ordered if node.cause_role in ("root", "main")],
                        secondary_groups=[
                            EventSecondaryGroupRow(target_event_id=target, branch=sorted(branch))
                            for target, branch in sorted(secondary_by_target.items())
                        ],
                        chapter_ids=sorted({node.chapter_id for node in nodes}),
                        char_start=min(node.char_start for node in nodes),
                        char_end=max(node.char_end for node in nodes),
                    ),
                    sort_key(ordered[0]),
                )
            )
        trees.sort(key=lambda pair: pair[1])
        return [tree for tree, _sort in trees]

    def fetch_snapshot(self, run_id: str, *, chapter_id: int | None = None) -> EventForestSnapshot | None:
        """2026-08-19 用于返回章节边界内的事件森林快照"""
        boundary = self.resolve_chapter_boundary(run_id, chapter_id=chapter_id)
        if boundary is None:
            return None
        event_nodes = self.fetch_event_nodes(run_id, max_chapter_order=boundary.chapter_order)
        causal_edges = self.fetch_event_edges(run_id, max_chapter_order=boundary.chapter_order)
        foreshadowing_edges = self.fetch_foreshadowing_edges(run_id, max_chapter_order=boundary.chapter_order)
        visible_event_ids = {node.event_id for node in event_nodes}
        visible_threads = [
            ForeshadowingEdgeRow(
                setup_id=edge.setup_id,
                run_id=edge.run_id,
                setup_event_id=edge.setup_event_id,
                payoff_event_id=edge.payoff_event_id if edge.payoff_event_id in visible_event_ids else None,
                first_chapter_id=edge.first_chapter_id,
                last_chapter_id=(
                    edge.last_chapter_id
                    if edge.payoff_event_id in visible_event_ids or edge.payoff_event_id is None
                    else edge.first_chapter_id
                ),
                setup_summary=edge.setup_summary,
                status=edge.status
                if edge.payoff_event_id in visible_event_ids or edge.payoff_event_id is None
                else "open",
                active=edge.active
                if edge.payoff_event_id in visible_event_ids or edge.payoff_event_id is None
                else True,
            )
            for edge in foreshadowing_edges
        ]
        ordered_nodes = sorted(
            event_nodes, key=lambda node: (node.chapter_order, node.char_start, node.char_end, node.event_id)
        )
        return EventForestSnapshot(
            chapter_id=boundary.chapter_id,
            chapter_order=boundary.chapter_order,
            visible_through_chapter_order=boundary.chapter_order,
            derived_event_order=[node.event_id for node in ordered_nodes],
            event_nodes=event_nodes,
            event_trees=self._build_event_trees(event_nodes),
            causal_edges=causal_edges,
            foreshadowing_edges=visible_threads,
        )
