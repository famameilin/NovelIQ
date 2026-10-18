"""事件森林与时间轴的读侧装配

把仓储层的事件森林快照（EventForestSnapshot）转成 API 响应 DTO；手工装配集中在此，
路由只做依赖注入与取数编排。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

from src.api.models.events import (
    EventEdgeResponse,
    EventForestResponse,
    EventNodeResponse,
    EventSecondaryGroupResponse,
    EventTimelineCausalEdge,
    EventTreeResponse,
    ForeshadowingEdgeResponse,
)

if TYPE_CHECKING:
    from src.event_trees.read.models import EventForestSnapshot


def build_event_forest_response(snapshot: EventForestSnapshot) -> EventForestResponse:
    """组装事件森林响应 DTO"""
    return EventForestResponse(
        chapter_id=snapshot.chapter_id,
        chapter_order=snapshot.chapter_order,
        visible_through_chapter_order=snapshot.visible_through_chapter_order,
        derived_event_order=snapshot.derived_event_order,
        event_nodes=[
            EventNodeResponse(
                event_id=node.event_id,
                chapter_id=node.chapter_id,
                chapter_order=node.chapter_order,
                description=node.description,
                participants=node.participants,
                anchor_paragraph_ids=node.anchor_paragraph_ids,
                char_start=node.char_start,
                char_end=node.char_end,
                evidence=node.evidence,
                causal_event_refs=node.causal_event_refs,
                tree_id=node.tree_id,
                cause_role=cast(Literal["root", "main", "secondary"], node.cause_role),
                parent_event_id=node.parent_event_id,
                evidence_scope=cast(Literal["chapter", "paragraph"], node.evidence_scope),
            )
            for node in snapshot.event_nodes
        ],
        event_trees=[
            EventTreeResponse(
                tree_id=tree.tree_id,
                root_event_id=tree.root_event_id,
                main_chain=tree.main_chain,
                secondary_groups=[
                    EventSecondaryGroupResponse(
                        target_event_id=group.target_event_id,
                        branch=group.branch,
                    )
                    for group in tree.secondary_groups
                ],
                chapter_ids=tree.chapter_ids,
                char_start=tree.char_start,
                char_end=tree.char_end,
            )
            for tree in snapshot.event_trees
        ],
        causal_edges=[
            EventEdgeResponse(
                edge_id=edge.edge_id,
                edge_type=cast(Literal["causal"], edge.edge_type),
                source_event_id=edge.source_event_id,
                target_event_id=edge.target_event_id,
                source_chapter_id=edge.source_chapter_id,
                target_chapter_id=edge.target_chapter_id,
                is_active=edge.is_active,
                evidence=edge.evidence,
            )
            for edge in snapshot.causal_edges
        ],
        foreshadowing_edges=[
            ForeshadowingEdgeResponse(
                root_event_id=fe.root_event_id,
                tree_id=fe.tree_id,
                payoff_event_id=fe.payoff_event_id,
                first_chapter_id=fe.first_chapter_id,
                last_chapter_id=fe.last_chapter_id,
                description=fe.description,
                status=fe.status,
                active=fe.active,
            )
            for fe in snapshot.foreshadowing_edges
        ],
    )


def serialize_snapshot_edges(
    snapshot: EventForestSnapshot,
) -> tuple[list[EventTimelineCausalEdge], list[ForeshadowingEdgeResponse]]:
    """序列化事件森林快照中的边（时间轴合同：因果边含 expired_at）"""
    causal = [
        EventTimelineCausalEdge(
            edge_id=e.edge_id,
            edge_type="causal",
            source_event_id=e.source_event_id,
            target_event_id=e.target_event_id,
            source_chapter_id=e.source_chapter_id,
            target_chapter_id=e.target_chapter_id,
            is_active=e.is_active,
            evidence=list(e.evidence),
            expired_at=e.expired_at,
        )
        for e in snapshot.causal_edges
    ]
    foreshadowing = [
        ForeshadowingEdgeResponse(
            root_event_id=e.root_event_id,
            payoff_event_id=e.payoff_event_id,
            first_chapter_id=e.first_chapter_id,
            last_chapter_id=e.last_chapter_id,
            tree_id=e.tree_id,
            description=e.description,
            status=e.status,
            active=e.active,
        )
        for e in snapshot.foreshadowing_edges
    ]
    return causal, foreshadowing
