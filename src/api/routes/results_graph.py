"""
图结构与事件森林结果查询路由

说明: 从 src/api/routes/results.py 拆出图快照/图变化/图指标/关键词与事件森林域路由，
手工 DTO 装配抽为模块内 converter（_build_event_forest_response），行为保持不变。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.models.events import (
    EventForestResponse,
    EventSourceChapterResponse,
    EventSourceParagraphResponse,
)
from src.api.models.graph import (
    GraphChangesResponse,
    GraphMetricsResponse,
    GraphSnapshotResponse,
    KeywordsResponse,
)
from src.api.routes.results_common import (
    _require_readable_run_status,
    _require_run_for_novel,
    get_db_session,
    resolve_run_id,
)
from src.api.services.results_queries import (
    _fetch_graph_changes_page,
    _fetch_graph_snapshot,
)
from src.api.services.results_queries.event_projection import build_event_forest_response
from src.api.services.results_queries.graph import GRAPH_CHANGE_LIMIT, compute_graph_metrics
from src.metrics.queries.keywords import query_keywords as compute_keywords
from src.storage import Storage

if TYPE_CHECKING:
    pass

# 说明: tags 由主模块 router（tags=["results"]）在 include 时统一附加，避免标签重复
router = APIRouter()


@router.get("/{novel_id}/graph", response_model=GraphSnapshotResponse)
async def get_graph(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Storage, Depends(get_db_session)],
    chapter_id: Annotated[int | None, Query(gt=0)] = None,
) -> GraphSnapshotResponse:
    """读取指定章节边界或最新章节的动态图快照"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    annotation_repo = session
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
    session: Annotated[Storage, Depends(get_db_session)],
    chapter_id: Annotated[int | None, Query(gt=0)] = None,
    changes_cursor: Annotated[str | None, Query(description="章节图变化分页 cursor")] = None,
    changes_limit: Annotated[int, Query(ge=1, le=GRAPH_CHANGE_LIMIT)] = GRAPH_CHANGE_LIMIT,
) -> GraphChangesResponse:
    """按章节分页读取实体状态与稳定关系变化"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    annotation_repo = session
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
    session: Annotated[Storage, Depends(get_db_session)],
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
    session: Annotated[Storage, Depends(get_db_session)],
    top_n: int = Query(default=10, ge=1, le=50),
) -> KeywordsResponse:
    """
    TextRank 关键词（赛道 A3）：独立词共现图 + PageRank

    与 LDA 主题词口径独立，可对照不可混用。
    """
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    return KeywordsResponse(**compute_keywords(run_id, session, top_n=top_n))


# 说明: event-forest 路由在原注册顺序中位于 metrics/* 之后，独立成 router 以保持主模块注册顺序一致
event_forest_router = APIRouter()


@event_forest_router.get("/{novel_id}/event-forest", response_model=EventForestResponse)
async def get_event_forest(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Storage, Depends(get_db_session)],
    chapter_id: Annotated[int | None, Query(gt=0)] = None,
) -> EventForestResponse:
    """查询事件树、树间边、锚点、证据、可见边界和派生顺序"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    from src.event_trees.read.forest import EventForestQuery

    repo = EventForestQuery(session)
    try:
        snapshot = repo.fetch_snapshot(
            run_id,
            chapter_id=chapter_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if snapshot is None:
        raise HTTPException(status_code=404, detail="当前 run 尚无匹配的章节图数据")
    return build_event_forest_response(snapshot)


@event_forest_router.get(
    "/{novel_id}/event-forest/chapters/{chapter_id}/source",
    response_model=EventSourceChapterResponse,
)
async def get_event_source_chapter(
    novel_id: str,
    chapter_id: int,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Storage, Depends(get_db_session)],
) -> EventSourceChapterResponse:
    """按需读取当前任务的一章原文，供事件树节点核对依据"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    chapter = session.reads.api_routes_results_graph_get_event_source_chapter_1(chapter_id, run_id)
    if chapter is None or chapter.text is None:
        raise HTTPException(status_code=404, detail="当前任务没有该章节原文")
    paragraphs = list(session.reads.api_routes_results_graph_get_event_source_chapter_2(chapter_id, run_id))
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
