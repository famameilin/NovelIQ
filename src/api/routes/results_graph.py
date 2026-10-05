"""
图结构与事件森林结果查询路由

创建时间: 2026-10-02
创建者: Trae
任务: 大文件拆分（routes/results.py → 同目录资源域子模块）
说明: 从 src/api/routes/results.py 拆出图快照/图变化/图指标/关键词与事件森林域路由，
手工 DTO 装配抽为模块内 converter（_build_event_forest_response），行为保持不变。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.models.event_forest import (
    EventEdgeResponse,
    EventForestResponse,
    EventNodeResponse,
    EventSecondaryGroupResponse,
    EventSourceChapterResponse,
    EventSourceParagraphResponse,
    EventTreeResponse,
    ForeshadowingEdgeResponse,
)
from src.api.models.graph import GraphChangesResponse, GraphMetricsResponse, GraphSnapshotResponse, KeywordsResponse
from src.api.routes.results_common import (
    _require_readable_run_status,
    _require_run_for_novel,
    get_db_session,
    resolve_run_id,
)
from src.api.routes.results_fetchers import (
    _fetch_graph_changes_page,
    _fetch_graph_snapshot,
)
from src.api.services.results_queries.graph import GRAPH_CHANGE_LIMIT
from src.api.services.results_queries.graph_metrics import compute_graph_metrics
from src.api.services.results_queries.keywords import compute_keywords
from src.storage.models import Chapter, Paragraph
from src.storage.repositories import AnnotationRepository

if TYPE_CHECKING:
    from src.storage.repositories.graph.event_forest import EventForestSnapshot

# 说明: tags 由主模块 router（tags=["results"]）在 include 时统一附加，避免标签重复
router = APIRouter()


@router.get("/{novel_id}/graph", response_model=GraphSnapshotResponse)
async def get_graph(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
    chapter_id: Annotated[int | None, Query(gt=0)] = None,
) -> GraphSnapshotResponse:
    """2026-08-07 用于读取指定章节边界或最新章节的动态图快照"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    annotation_repo = AnnotationRepository(session)
    try:
        payload = _fetch_graph_snapshot(
            run_id,
            annotation_repo,
            chapter_id=chapter_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return GraphSnapshotResponse.model_validate(payload)


@router.get("/{novel_id}/graph/changes", response_model=GraphChangesResponse)
async def get_graph_changes(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
    chapter_id: Annotated[int | None, Query(gt=0)] = None,
    changes_cursor: Annotated[str | None, Query(description="章节图变化分页 cursor")] = None,
    changes_limit: Annotated[int, Query(ge=1, le=GRAPH_CHANGE_LIMIT)] = GRAPH_CHANGE_LIMIT,
) -> GraphChangesResponse:
    """2026-08-07 用于按章节分页读取实体状态与稳定关系变化"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    annotation_repo = AnnotationRepository(session)
    try:
        payload = _fetch_graph_changes_page(
            run_id,
            annotation_repo,
            chapter_id=chapter_id,
            changes_cursor=changes_cursor,
            changes_limit=changes_limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GraphChangesResponse.model_validate(payload)


@router.get("/{novel_id}/graph/metrics", response_model=GraphMetricsResponse)
async def get_graph_metrics(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> GraphMetricsResponse:
    """
    人物关系图结构指标（赛道 A1/A2）：PageRank / HITS / Louvain

    查询时计算；输入为代表性人物子图（别名归并、边权=关系计数），
    结构社区不直接等同于故事阵营。
    """
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    return GraphMetricsResponse(**compute_graph_metrics(run_id, session))


@router.get("/{novel_id}/keywords", response_model=KeywordsResponse)
async def get_keywords(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
    top_n: int = Query(default=10, ge=1, le=50),
) -> KeywordsResponse:
    """
    TextRank 关键词（赛道 A3）：独立词共现图 + PageRank

    与 LDA 主题词口径独立，可对照不可混用。
    """
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    return KeywordsResponse(**compute_keywords(run_id, session, top_n=top_n))


def _build_event_forest_response(snapshot: EventForestSnapshot) -> EventForestResponse:
    """组装事件森林响应 DTO（2026-10-02 自路由体抽取的手工装配 converter）"""
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


# 说明: event-forest 路由在原注册顺序中位于 metrics/* 之后，独立成 router 以保持主模块注册顺序一致
event_forest_router = APIRouter()


@event_forest_router.get("/{novel_id}/event-forest", response_model=EventForestResponse)
async def get_event_forest(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
    chapter_id: Annotated[int | None, Query(gt=0)] = None,
) -> EventForestResponse:
    """查询事件树、树间边、锚点、证据、可见边界和派生顺序"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    from src.storage.repositories.graph import EventForestRepository

    repo = EventForestRepository(session)
    try:
        snapshot = repo.fetch_snapshot(
            run_id,
            chapter_id=chapter_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if snapshot is None:
        raise HTTPException(status_code=404, detail="当前 run 尚无匹配的章节图数据")
    return _build_event_forest_response(snapshot)


@event_forest_router.get(
    "/{novel_id}/event-forest/chapters/{chapter_id}/source",
    response_model=EventSourceChapterResponse,
)
async def get_event_source_chapter(
    novel_id: str,
    chapter_id: int,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> EventSourceChapterResponse:
    """按需读取当前任务的一章原文，供事件树节点核对依据"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    chapter = session.get(Chapter, (chapter_id, run_id))
    if chapter is None or chapter.text is None:
        raise HTTPException(status_code=404, detail="当前任务没有该章节原文")
    paragraphs = list(
        session.execute(
            select(Paragraph)
            .where(Paragraph.run_id == run_id, Paragraph.chapter_id == chapter_id)
            .order_by(Paragraph.paragraph_index)
        ).scalars()
    )
    if not paragraphs:
        raise HTTPException(status_code=404, detail="当前任务没有该章节原文段落")
    return EventSourceChapterResponse(
        chapter_id=chapter_id,
        title=chapter.display_title or chapter.title,
        paragraphs=[
            EventSourceParagraphResponse(
                paragraph_id=paragraph.paragraph_id,
                paragraph_index=paragraph.paragraph_index,
                text=paragraph.text,
            )
            for paragraph in paragraphs
        ],
    )
