"""章节事件森林查询 Repository"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
    expired_at: datetime | None = None


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

    def _chapter_ids_for_order(
        self, run_id: str, max_chapter_order: int, *, chapters: list[Chapter] | None = None
    ) -> set[int]:
        """2026-08-19 用于按 chapter_order 解析可见章节集合（复用已缓存 chapters 避免 N+1）"""
        if chapters is None:
            chapters = self._chapter_rows(run_id)
        return {
            int(chapter.chapter_id) for index, chapter in enumerate(chapters, start=1) if index <= max_chapter_order
        }

    def resolve_chapter_boundary(
        self,
        run_id: str,
        *,
        chapter_id: int | None = None,
        chapters: list[Chapter] | None = None,
    ) -> ChapterBoundary | None:
        """2026-08-19 用于按章节身份解析当前运行的图谱边界（缓存 chapters，批量查 annotation 避免逆序 N+1）"""
        if chapters is None:
            chapters = self._chapter_rows(run_id)
        if chapter_id is None:
            if not chapters:
                return None
            # 批量查询 annotation 避免逆序 N+1
            chapter_ids = [int(c.chapter_id) for c in chapters]
            rows = list(
                self.session.execute(
                    select(ChapterAnnotationRecord).where(
                        ChapterAnnotationRecord.run_id == run_id,
                        ChapterAnnotationRecord.chapter_id.in_(chapter_ids),
                    )
                ).scalars()
            )
            annotation_by_chapter: dict[int, ChapterAnnotationRecord] = {int(row.chapter_id): row for row in rows}
            target = None
            annotation = None
            for candidate in reversed(chapters):
                cand_annotation = annotation_by_chapter.get(int(candidate.chapter_id))
                if cand_annotation is not None:
                    target = candidate
                    annotation = cand_annotation
                    break
            if target is None or annotation is None:
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

    def fetch_event_edges(
        self,
        run_id: str,
        *,
        max_chapter_order: int,
        include_inactive: bool = False,
        chapters: list[Chapter] | None = None,
    ) -> list[EventEdgeRow]:
        """2026-08-19 用于读取截止章节边界的因果边（支持复用已缓存 chapters）"""
        chapter_ids = self._chapter_ids_for_order(run_id, max_chapter_order, chapters=chapters)
        if not chapter_ids:
            return []
        return self._fetch_event_edges_by_chapter_ids(run_id, chapter_ids, include_inactive=include_inactive)

    def _fetch_event_edges_by_chapter_ids(
        self, run_id: str, chapter_ids: set[int], *, include_inactive: bool = False
    ) -> list[EventEdgeRow]:
        """内部：按已解析 chapter_ids 查询因果边，避免重复计算章节集合"""
        if not chapter_ids:
            return []
        filters: list[Any] = [
            EventEdge.run_id == run_id,
            EventEdge.source_chapter_id.in_(chapter_ids),
            EventEdge.target_chapter_id.in_(chapter_ids),
        ]
        if not include_inactive:
            filters.append(EventEdge.is_active.is_(True))
        rows = self.session.execute(select(EventEdge).where(*filters).order_by(EventEdge.edge_id)).scalars()
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
                expired_at=edge.expired_at,
            )
            for edge in rows
        ]

    def fetch_timeline_causal_edges(
        self, run_id: str, *, max_chapter_order: int, chapters: list[Chapter] | None = None
    ) -> list[EventEdgeRow]:
        """2026-08-20 用于时间轴返回全量因果边（含 inactive，前端灰显）"""
        return self.fetch_event_edges(
            run_id, max_chapter_order=max_chapter_order, include_inactive=True, chapters=chapters
        )

    def fetch_foreshadowing_edges(
        self,
        run_id: str,
        *,
        max_chapter_order: int,
        chapters: list[Chapter] | None = None,
    ) -> list[ForeshadowingEdgeRow]:
        """2026-08-19 用于读取截止章节边界的伏笔边（支持复用已缓存 chapters）"""
        chapter_ids = self._chapter_ids_for_order(run_id, max_chapter_order, chapters=chapters)
        if not chapter_ids:
            return []
        return self._fetch_foreshadowing_edges_by_chapter_ids(run_id, chapter_ids)

    def _fetch_foreshadowing_edges_by_chapter_ids(
        self, run_id: str, chapter_ids: set[int]
    ) -> list[ForeshadowingEdgeRow]:
        """内部：按已解析 chapter_ids 查询伏笔边"""
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
        """2026-08-19 用于返回章节边界内的事件森林快照（单次缓存 chapters，避免 4 次 _chapter_rows + 逆序 N+1）"""
        chapters = self._chapter_rows(run_id)
        boundary = self.resolve_chapter_boundary(run_id, chapter_id=chapter_id, chapters=chapters)
        if boundary is None:
            return None
        event_nodes = self.fetch_event_nodes(run_id, max_chapter_order=boundary.chapter_order)
        # 复用已缓存 chapters 解析可见章节集合，单次计算供两类边复用
        visible_chapter_ids = self._chapter_ids_for_order(run_id, boundary.chapter_order, chapters=chapters)
        causal_edges = self._fetch_event_edges_by_chapter_ids(run_id, visible_chapter_ids, include_inactive=True)
        foreshadowing_edges = self._fetch_foreshadowing_edges_by_chapter_ids(run_id, visible_chapter_ids)
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
