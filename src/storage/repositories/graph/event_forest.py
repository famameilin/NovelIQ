"""
事件森林/DAG 查询 Repository

2026-08-18 P2：事件过程层正式接管后提供查询入口。按章节边界暴露已授权历史
事件、事件边和 Evidence，供 Agent 事件可见性查询和 API 端点使用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.models import EventEdge, EventNode, ForeshadowingThread, GraphVersion


@dataclass(frozen=True)
class EventNodeRow:
    """2026-08-18 用于返回事件节点快照"""

    event_id: str
    event_revision: int
    chapter_id: int
    chapter_order: int
    description: str
    participants: list[dict[str, Any]]
    anchor_paragraph_ids: list[int]
    char_start: int
    char_end: int
    text_hash: str
    evidence: list[dict[str, Any]]
    causal_event_refs: list[int]


@dataclass(frozen=True)
class EventEdgeRow:
    """2026-08-18 用于返回事件边快照"""

    edge_id: str
    edge_type: str
    source_event_id: str | None
    source_event_revision: int | None
    target_event_id: str
    target_event_revision: int
    source_chapter_id: int
    target_chapter_id: int
    is_active: bool
    evidence: list[dict[str, Any]]


@dataclass(frozen=True)
class ForeshadowingEdgeRow:
    """2026-08-18 用于返回伏笔边（线程即边）快照"""

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
class EventChapterRootRow:
    """2026-08-18 用于返回章节根及其 contains 事件顺序"""

    chapter_id: int
    chapter_order: int
    event_ids: list[str]


@dataclass(frozen=True)
class EventForestSnapshot:
    """2026-08-18 用于返回完整事件森林快照"""

    chapter_order: int
    graph_version_id: str
    visible_through_chapter_order: int
    chapter_roots: list[EventChapterRootRow]
    derived_event_order: list[str]
    event_nodes: list[EventNodeRow]
    event_edges: list[EventEdgeRow]
    foreshadowing_edges: list[ForeshadowingEdgeRow]


class EventForestRepository:
    """2026-08-18 用于查询事件森林/DAG 快照"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def _chapter_ids_for_order(self, run_id: str, max_chapter_order: int) -> set[int]:
        """2026-08-18 用于把已完成图版本的 chapter_order 转换为章节边界集合"""
        return {
            int(chapter_id)
            for chapter_id in self.session.execute(
                select(GraphVersion.chapter_id).where(
                    GraphVersion.run_id == run_id,
                    GraphVersion.chapter_order <= max_chapter_order,
                )
            ).scalars()
        }

    def resolve_graph_version(
        self,
        run_id: str,
        *,
        chapter_id: int | None = None,
        graph_version_id: str | None = None,
    ) -> GraphVersion | None:
        """2026-08-18 用于按 chapter_id 或 graph_version_id 解析当前 run 的图版本边界"""
        if chapter_id is not None and graph_version_id is not None:
            raise ValueError("chapter_id 与 graph_version_id 只能二选一")
        if graph_version_id is not None:
            return self.session.execute(
                select(GraphVersion).where(
                    GraphVersion.run_id == run_id,
                    GraphVersion.graph_version_id == graph_version_id,
                )
            ).scalar_one_or_none()
        if chapter_id is not None:
            return self.session.execute(
                select(GraphVersion)
                .where(
                    GraphVersion.run_id == run_id,
                    GraphVersion.chapter_id == chapter_id,
                )
                .order_by(GraphVersion.chapter_order.desc())
            ).scalar_one_or_none()
        # 无指定时取最新图版本
        return self.session.execute(
            select(GraphVersion)
            .where(GraphVersion.run_id == run_id)
            .order_by(GraphVersion.chapter_order.desc())
            .limit(1)
        ).scalar_one_or_none()

    def fetch_event_nodes(
        self,
        run_id: str,
        *,
        max_chapter_order: int,
    ) -> list[EventNodeRow]:
        """2026-08-18 用于读取截止指定章节边界的全部事件节点最新修订"""
        rows = self.session.execute(
            select(EventNode)
            .where(
                EventNode.run_id == run_id,
                EventNode.chapter_order <= max_chapter_order,
            )
            .order_by(EventNode.chapter_order, EventNode.event_id, EventNode.event_revision.desc())
        ).scalars()
        # 每个事件只取最新修订
        latest: dict[str, EventNode] = {}
        for node in rows:
            latest.setdefault(node.event_id, node)
        return [
            EventNodeRow(
                event_id=node.event_id,
                event_revision=node.event_revision,
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
            )
            for node in sorted(latest.values(), key=lambda n: (n.chapter_order, n.event_id))
        ]

    def fetch_event_edges(
        self,
        run_id: str,
        *,
        max_chapter_order: int,
    ) -> list[EventEdgeRow]:
        """2026-08-18 用于读取截止指定章节边界的全部活跃事件边"""
        chapter_ids = self._chapter_ids_for_order(run_id, max_chapter_order)
        if not chapter_ids:
            return []
        rows = self.session.execute(
            select(EventEdge)
            .where(
                EventEdge.run_id == run_id,
                EventEdge.is_active == 1,
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
                source_event_revision=edge.source_event_revision,
                target_event_id=edge.target_event_id,
                target_event_revision=edge.target_event_revision,
                source_chapter_id=edge.source_chapter_id,
                target_chapter_id=edge.target_chapter_id,
                is_active=bool(edge.is_active),
                evidence=list(edge.evidence),
            )
            for edge in rows
        ]

    def fetch_foreshadowing_edges(
        self,
        run_id: str,
        *,
        max_chapter_order: int,
    ) -> list[ForeshadowingEdgeRow]:
        """2026-08-18 用于读取伏笔边（线程即边）"""
        chapter_ids = self._chapter_ids_for_order(run_id, max_chapter_order)
        if not chapter_ids:
            return []
        rows = self.session.execute(
            select(ForeshadowingThread)
            .where(
                ForeshadowingThread.run_id == run_id,
                ForeshadowingThread.first_chapter_id.in_(chapter_ids),
            )
            .order_by(ForeshadowingThread.first_chapter_id)
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

    def fetch_snapshot(
        self,
        run_id: str,
        *,
        chapter_id: int | None = None,
        graph_version_id: str | None = None,
    ) -> EventForestSnapshot | None:
        """2026-08-18 用于返回完整事件森林快照（章节根、事件节点、三类边、锚点、Evidence、可见边界和派生顺序）"""
        boundary = self.resolve_graph_version(
            run_id,
            chapter_id=chapter_id,
            graph_version_id=graph_version_id,
        )
        if boundary is None:
            return None
        max_order = int(boundary.chapter_order)
        event_nodes = self.fetch_event_nodes(run_id, max_chapter_order=max_order)
        event_edges = self.fetch_event_edges(run_id, max_chapter_order=max_order)
        foreshadowing_edges = self.fetch_foreshadowing_edges(
            run_id,
            max_chapter_order=max_order,
        )
        visible_event_ids = {node.event_id for node in event_nodes}
        foreshadowing_edges = [
            ForeshadowingEdgeRow(
                setup_id=edge.setup_id,
                run_id=edge.run_id,
                setup_event_id=edge.setup_event_id,
                payoff_event_id=(
                    edge.payoff_event_id
                    if edge.payoff_event_id in visible_event_ids
                    else None
                ),
                first_chapter_id=edge.first_chapter_id,
                last_chapter_id=(
                    edge.last_chapter_id
                    if edge.payoff_event_id in visible_event_ids or edge.payoff_event_id is None
                    else edge.first_chapter_id
                ),
                setup_summary=edge.setup_summary,
                status=(
                    edge.status
                    if edge.payoff_event_id in visible_event_ids or edge.payoff_event_id is None
                    else "open"
                ),
                active=(
                    edge.active
                    if edge.payoff_event_id in visible_event_ids or edge.payoff_event_id is None
                    else True
                ),
            )
            for edge in foreshadowing_edges
        ]
        roots_by_chapter: dict[int, EventChapterRootRow] = {}
        for node in event_nodes:
            root = roots_by_chapter.setdefault(
                node.chapter_id,
                EventChapterRootRow(
                    chapter_id=node.chapter_id,
                    chapter_order=node.chapter_order,
                    event_ids=[],
                ),
            )
            root.event_ids.append(node.event_id)
        chapter_roots = sorted(
            roots_by_chapter.values(),
            key=lambda root: (root.chapter_order, root.chapter_id),
        )
        derived_event_order = [
            node.event_id
            for node in sorted(
                event_nodes,
                key=lambda node: (
                    node.chapter_order,
                    node.char_start,
                    node.char_end,
                    node.event_id,
                ),
            )
        ]
        return EventForestSnapshot(
            chapter_order=max_order,
            graph_version_id=boundary.graph_version_id,
            visible_through_chapter_order=max_order,
            chapter_roots=chapter_roots,
            derived_event_order=derived_event_order,
            event_nodes=event_nodes,
            event_edges=event_edges,
            foreshadowing_edges=foreshadowing_edges,
        )
