"""事件森林时间轴 API 路由"""

from __future__ import annotations

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Query, Response
from loguru import logger
from sqlalchemy.orm import Session

from src.api.dependencies import get_db_session, get_novel_service
from src.api.exceptions import AnalysisNotCompleteError, NovelNotFoundError
from src.api.models.event_timeline import (
    EventTimelineCausalEdge,
    EventTimelineForeshadowingEdge,
    EventTimelineMeta,
    EventTimelineNode,
    EventTimelinePhase,
    EventTimelineResponse,
)
from src.api.models.responses import ErrorResponse
from src.api.services.novel_service import NovelService
from src.metrics.event_timeline_metrics import (
    build_event_timeline_plan,
    serialize_event_timeline_node,
    serialize_event_timeline_phases,
)
from src.storage.repositories import ChapterRepository, RunRepository, StatsRepository
from src.storage.repositories.graph import EventForestRepository
from src.storage.repositories.graph.event_forest import EventForestSnapshot

router = APIRouter(prefix="/novels", tags=["timeline"])


def _serialize_snapshot_edges(
    snapshot: EventForestSnapshot,
) -> tuple[list[EventTimelineCausalEdge], list[EventTimelineForeshadowingEdge]]:
    """序列化事件森林快照中的边"""
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
        EventTimelineForeshadowingEdge(
            setup_id=e.setup_id,
            setup_event_id=e.setup_event_id,
            payoff_event_id=e.payoff_event_id,
            first_chapter_id=e.first_chapter_id,
            last_chapter_id=e.last_chapter_id,
            setup_summary=e.setup_summary,
            status=e.status,
            active=e.active,
        )
        for e in snapshot.foreshadowing_edges
    ]
    return causal, foreshadowing


@router.get(
    "/{novel_id}/timeline",
    response_model=EventTimelineResponse,
    summary="获取事件森林时间轴（一树一节点）",
    description="基于事件森林快照与段落张力生成一树一节点的时间轴视图",
    responses={
        200: {
            "description": "时间轴数据",
        },
        404: {
            "description": "小说或任务未找到",
            "model": ErrorResponse,
        },
        400: {
            "description": "分析未完成",
            "model": ErrorResponse,
        },
    },
)
async def get_timeline(
    novel_id: str,
    task_id: Annotated[str, Query(description="分析任务ID（8位短UUID）")],
    session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[NovelService, Depends(get_novel_service)],
    response: Response,
    include_curve: Annotated[bool, Query(description="是否包含张力曲线数据")] = False,
) -> EventTimelineResponse:
    """获取事件森林时间轴数据"""

    novels = service.list_novels()
    novel_info = next((novel for novel in novels if novel.get("novel_id") == novel_id), None)
    if novel_info is None:
        raise NovelNotFoundError(f"小说不存在: {novel_id}")

    novel_name = novel_info.get("filename", "未知")
    run_repo = RunRepository(session)
    run_data = run_repo.get_run_by_run_id_prefix(task_id)
    if run_data is None:
        raise NovelNotFoundError(f"任务不存在: {task_id}")

    if run_data.get("novel_id") != novel_id:
        raise NovelNotFoundError(f"任务 {task_id} 不属于小说 {novel_id}")

    run_id = run_data["run_id"]
    if run_data["status"] not in ("completed",):
        raise AnalysisNotCompleteError(
            f"分析尚未完成，当前状态: {run_data['status']}",
            run_status=run_data["status"],
        )
    chapter_repo = ChapterRepository(session)
    stats_repo = StatsRepository(session)

    snapshot = EventForestRepository(session).fetch_snapshot(run_id, chapter_id=None)
    if snapshot is None:
        logger.warning("No event forest snapshot for run {}", run_id)
        response.headers["X-Timeline-Empty-Reason"] = "no_event_forest"
        return EventTimelineResponse(
            meta=EventTimelineMeta(
                novel_id=novel_id,
                novel_name=novel_name,
                total_chapters=0,
            ),
            phases=[],
            nodes=[],
            causal_edges=[],
            foreshadowing_edges=[],
            derived_event_order=[],
            tension_curve=None,
            phase_basis="tension",
            total_chapters=0,
        )

    timeline_plan = build_event_timeline_plan(
        run_id,
        chapter_repo,
        stats_repo,
        snapshot,
    )

    api_nodes = [EventTimelineNode.model_validate(serialize_event_timeline_node(node)) for node in timeline_plan.nodes]
    api_phases = [
        EventTimelinePhase.model_validate(item) for item in serialize_event_timeline_phases(timeline_plan.phases)
    ]
    api_causal_edges, api_foreshadowing_edges = _serialize_snapshot_edges(snapshot)

    if api_nodes:
        logger.info(
            "Event timeline generated for novel {} task {}: {} nodes, {} phases, {} causal edges",
            novel_id,
            task_id,
            len(api_nodes),
            len(api_phases),
            len(api_causal_edges),
        )
    else:
        logger.info("Timeline empty for run {}: {} phases, 0 nodes", run_id, len(api_phases))

    return EventTimelineResponse(
        meta=EventTimelineMeta(
            novel_id=novel_id,
            novel_name=novel_name,
            total_chapters=timeline_plan.total_chapters,
        ),
        phases=api_phases,
        nodes=api_nodes,
        causal_edges=api_causal_edges,
        foreshadowing_edges=api_foreshadowing_edges,
        derived_event_order=timeline_plan.derived_event_order,
        tension_curve=timeline_plan.tension_curve if include_curve else None,
        phase_basis=cast(Literal["tension", "fixed_percentage"], timeline_plan.phase_basis),
        total_chapters=timeline_plan.total_chapters,
    )
