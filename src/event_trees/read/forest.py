"""事件森林读视图、树内排序与伏笔解释；原始 SQL 由 storage 提供"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.event_trees.read.models import (
    EventEdgeRow,
    EventForestSnapshot,
    EventNodeRow,
    EventSecondaryGroupRow,
    EventTreeRow,
    ForeshadowingEdgeRow,
)
from src.event_trees.read.order import formal_event_ordinals
from src.storage.models.graph import ChapterBoundary
from src.storage.repositories.graph.event_forest import EventForestRecords

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.storage.models import Chapter, EventEdge, EventNode


class EventForestQuery:
    """2026-08-19 用于查询章节事件森林"""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.records = EventForestRecords(session)

    def _chapter_rows(self, run_id: str) -> list[Chapter]:
        """2026-08-19 用于按章节身份读取有正文章节并确定排序"""
        return self.records.fetch_chapters(run_id)

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

        chapters = self._chapter_rows(run_id)
        records = {row.chapter_id: row for row in self.records.fetch_saved_outputs(run_id)}
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
            chapter_order=chapters.index(target) + 1,
            first_chapter_id=target.chapter_id,
            last_chapter_id=target.chapter_id,
            annotation_id=records[target.chapter_id].output_id,
        )

    def fetch_event_nodes(self, run_id: str, *, max_chapter_order: int) -> list[EventNodeRow]:
        """读取边界内节点，并从正式章标注恢复树内父节点与证据粒度"""
        rows = self.records.fetch_nodes(run_id, max_chapter_order)
        if not rows:
            return []
        annotation_ids = {node.annotation_id for node in rows}
        annotations = self.records.fetch_outputs(annotation_ids)
        # 不可变产出用于排序；父边和树归属读取当前有效连接的折叠结果
        payload_events: dict[str, dict[str, Any]] = {}
        for annotation in annotations:
            for event in annotation.payload["events"]:
                payload_events[event["node_id"]] = event
        ordinals = formal_event_ordinals(annotations)
        node_by_id = {node.event_id: node for node in rows}

        def parent_event_id(node: EventNode) -> str | None:
            parent_id = node.parent_node_id
            parent = node_by_id.get(str(parent_id)) if parent_id else None
            return str(parent_id) if parent is not None and parent.tree_id == node.tree_id else None

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
                evidence=list(node.evidence),
                causal_event_refs=list(node.causal_event_refs),
                tree_id=node.tree_id,
                cause_role=node.cause_role,
                parent_event_id=parent_event_id(node),
                evidence_scope="paragraph",
                payload_path=node.payload_path,
                event_ordinal=ordinals[node.event_id],
            )
            for node in rows
        ]

    def _fetch_event_edges_by_chapter_ids(
        self, run_id: str, chapter_ids: set[int], *, include_inactive: bool = False
    ) -> list[EventEdgeRow]:
        """按可见章节读取因果边，伏笔关联由独立通道返回"""
        if not chapter_ids:
            return []
        rows = self.records.fetch_causal_edges(run_id, chapter_ids, include_inactive=include_inactive)
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

    def _fetch_foreshadowing_edges_by_chapter_ids(
        self, run_id: str, chapter_ids: set[int]
    ) -> list[ForeshadowingEdgeRow]:
        """内部：按已解析 chapter_ids 查询伏笔树（根在可见章节内的树）"""
        if not chapter_ids:
            return []
        root_rows = self.records.fetch_foreshadow_roots(run_id, chapter_ids)
        roots = list(root_rows)
        if not roots:
            return []
        edges_by_root: dict[str, list[EventEdge]] = {}
        for edge in self.records.fetch_foreshadow_edges(run_id):
            edges_by_root.setdefault(edge.source_event_id, []).append(edge)
        return [
            ForeshadowingEdgeRow(
                root_event_id=root.event_id,
                run_id=run_id,
                tree_id=root.tree_id,
                payoff_event_id=None,
                first_chapter_id=root.chapter_id,
                last_chapter_id=max(
                    [root.chapter_id, *(edge.target_chapter_id for edge in edges_by_root.get(root.event_id, []))]
                ),
                description=root.description,
                status=root.foreshadowing_status or "open",
                active=(root.foreshadowing_status or "open") != "likely_paid_off",
            )
            for root in roots
        ]

    def _build_event_trees(self, event_nodes: list[EventNodeRow]) -> list[EventTreeRow]:
        """2026-08-19 用于按 tree_id 组装事件树视图"""
        nodes_by_tree: dict[str, list[EventNodeRow]] = {}
        for node in event_nodes:
            nodes_by_tree.setdefault(node.tree_id, []).append(node)

        def sort_key(node: EventNodeRow) -> tuple[int, int, int, str]:
            return node.chapter_order, node.char_start, node.event_ordinal, node.event_id

        trees: list[tuple[EventTreeRow, tuple[int, int, int, str]]] = []
        for tree_id, nodes in nodes_by_tree.items():
            ordered = sorted(nodes, key=sort_key)
            roots = [node for node in ordered if node.cause_role == "root"]
            root_id = roots[0].event_id if len(roots) == 1 else ordered[0].event_id
            secondary_by_target: dict[str, list[str]] = {}
            for node in ordered:
                if node.cause_role != "secondary":
                    continue
                # 缺失挂接点时保留旁支节点，以 tree_id 作为“未确定挂接”分组标记
                target = node.parent_event_id or tree_id
                secondary_by_target.setdefault(target, []).append(node.event_id)
            trees.append(
                (
                    EventTreeRow(
                        tree_id=tree_id,
                        root_event_id=root_id,
                        main_chain=[node.event_id for node in ordered if node.cause_role in ("root", "main")],
                        secondary_groups=[
                            EventSecondaryGroupRow(target_event_id=target, branch=branch)
                            for target, branch in secondary_by_target.items()
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
                root_event_id=edge.root_event_id,
                run_id=edge.run_id,
                tree_id=edge.tree_id,
                payoff_event_id=edge.payoff_event_id if edge.payoff_event_id in visible_event_ids else None,
                first_chapter_id=edge.first_chapter_id,
                last_chapter_id=(
                    edge.last_chapter_id
                    if edge.payoff_event_id in visible_event_ids or edge.payoff_event_id is None
                    else edge.first_chapter_id
                ),
                description=edge.description,
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
            event_nodes, key=lambda node: (node.chapter_order, node.char_start, node.event_ordinal, node.event_id)
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
