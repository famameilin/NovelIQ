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
    """2026-08-19 用于返回事件节点快照（契约 v3：含树结构字段）"""

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
    causal_event_refs: list[str]
    tree_id: str
    cause_role: str


@dataclass(frozen=True)
class EventEdgeRow:
    """2026-08-19 用于返回因果边快照（契约 v3：contains 不再落表，端点必为非空）"""

    edge_id: str
    edge_type: str
    source_event_id: str
    source_event_revision: int
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
class EventSecondaryGroupRow:
    """2026-08-19 用于返回一棵事件树的次因分支（挂在某个目标事件下）"""

    target_event_id: str
    branch: list[str]


@dataclass(frozen=True)
class EventTreeRow:
    """2026-08-19 用于返回一棵事件树（一棵树 = 一个完整事件）

    main_chain 为主因链（root + main 角色，按锚点原文顺序）；secondary_groups
    为次因分支（secondary 节点按其首个因果前驱 target 归组）。
    """

    tree_id: str
    root_event_id: str
    main_chain: list[str]
    secondary_groups: list[EventSecondaryGroupRow]
    chapter_ids: list[int]
    char_start: int
    char_end: int


@dataclass(frozen=True)
class EventForestSnapshot:
    """2026-08-19 用于返回完整事件森林快照（树视图 + 树间边，契约 v3）"""

    chapter_order: int
    graph_version_id: str
    visible_through_chapter_order: int
    derived_event_order: list[str]
    event_nodes: list[EventNodeRow]
    event_trees: list[EventTreeRow]
    causal_edges: list[EventEdgeRow]
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
                tree_id=node.tree_id,
                cause_role=node.cause_role,
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

    def _build_event_trees(self, event_nodes: list[EventNodeRow]) -> list[EventTreeRow]:
        """2026-08-19 用于按 tree_id 分组组装事件树视图（契约 v3）

        根 = cause_role 为 root 的唯一事件（缺失/多个时取锚点最早事件）；
        main_chain = root/main 角色按 (chapter_order, char_start) 原文顺序；
        secondary_groups = secondary 节点按首个因果前驱 target 归组。
        """
        nodes_by_tree: dict[str, list[EventNodeRow]] = {}
        for node in event_nodes:
            nodes_by_tree.setdefault(node.tree_id, []).append(node)

        def sort_key(node: EventNodeRow) -> tuple[int, int, int, str]:
            return (node.chapter_order, node.char_start, node.char_end, node.event_id)

        trees: list[tuple[EventTreeRow, tuple[int, int, int, str]]] = []
        for tree_id, nodes in nodes_by_tree.items():
            ordered = sorted(nodes, key=sort_key)
            roots = [n for n in ordered if n.cause_role == "root"]
            root_id = roots[0].event_id if len(roots) == 1 else ordered[0].event_id
            main_chain = [
                n.event_id
                for n in ordered
                if n.cause_role in ("root", "main")
            ]
            secondary_by_target: dict[str, list[str]] = {}
            for node in ordered:
                if node.cause_role != "secondary":
                    continue
                target = (
                    node.causal_event_refs[0]
                    if node.causal_event_refs
                    else tree_id
                )
                secondary_by_target.setdefault(target, []).append(node.event_id)
            secondary_groups = [
                EventSecondaryGroupRow(
                    target_event_id=target,
                    branch=sorted(branch),
                )
                for target, branch in sorted(secondary_by_target.items())
            ]
            trees.append(
                (
                    EventTreeRow(
                        tree_id=tree_id,
                        root_event_id=root_id,
                        main_chain=main_chain,
                        secondary_groups=secondary_groups,
                        chapter_ids=sorted({n.chapter_id for n in nodes}),
                        char_start=min(n.char_start for n in nodes),
                        char_end=max(n.char_end for n in nodes),
                    ),
                    sort_key(ordered[0]),
                )
            )
        trees.sort(key=lambda pair: pair[1])
        return [tree for tree, _ in trees]

    def fetch_snapshot(
        self,
        run_id: str,
        *,
        chapter_id: int | None = None,
        graph_version_id: str | None = None,
    ) -> EventForestSnapshot | None:
        """2026-08-19 用于返回完整事件森林快照（树视图 + 树间边，契约 v3）"""
        boundary = self.resolve_graph_version(
            run_id,
            chapter_id=chapter_id,
            graph_version_id=graph_version_id,
        )
        if boundary is None:
            return None
        max_order = int(boundary.chapter_order)
        event_nodes = self.fetch_event_nodes(run_id, max_chapter_order=max_order)
        causal_edges = self.fetch_event_edges(run_id, max_chapter_order=max_order)
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
        event_trees = self._build_event_trees(event_nodes)
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
            derived_event_order=derived_event_order,
            event_nodes=event_nodes,
            event_trees=event_trees,
            causal_edges=causal_edges,
            foreshadowing_edges=foreshadowing_edges,
        )
