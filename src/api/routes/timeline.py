"""
叙事时间轴 API 路由

说明: 提供时间轴数据查询接口，支持四阶段划分、节点筛选和张力曲线
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from loguru import logger
from sqlalchemy.orm import Session

from src.api.dependencies import get_db_session, get_novel_service
from src.api.exceptions import AnalysisNotCompleteError, NovelNotFoundError
from src.api.models.responses import ErrorResponse
from src.api.models.timeline import TimelineCompositeNode, TimelineMeta, TimelineNode, TimelinePhase, TimelineResponse
from src.api.services.novel_service import NovelService
from src.knowledge.authority import KnowledgeGraphAuthorityService
from src.metrics.timeline_metrics import (
    TimelineDataUnavailableError,
    build_timeline_plan,
    serialize_timeline_composite_node,
    serialize_timeline_node,
    serialize_timeline_phases,
)
from src.storage.repositories import AnnotationRepository, ChunkRepository, RunRepository, StatsRepository

router = APIRouter(prefix="/novels", tags=["timeline"])


@router.get(
    "/{novel_id}/timeline",
    response_model=TimelineResponse,
    summary="获取叙事时间轴",
    description="""
📊 **叙事时间轴接口**

基于张力曲线、知识图谱和标注数据，生成小说的时间轴视图。

**功能：**
- 四阶段划分（引入期/发展期/高潮期/收束期）
- 重要节点识别（剧情节点、关系变化节点、生命周期节点）
- 张力曲线数据
""",
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
    include_curve: Annotated[bool, Query(description="是否包含张力曲线数据")] = False,
) -> TimelineResponse:
    """
    获取叙事时间轴数据

    时间轴节点由 authority-backed timeline plan 直接生成，route 不再维护
    route-owned relation locator 补丁，避免 shared/export/frontend 再次漂移
    """

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
    if run_data["status"] not in ("completed", "aggregated", "diagnosed"):
        raise AnalysisNotCompleteError(
            f"分析尚未完成，当前状态: {run_data['status']}",
            run_status=run_data["status"],
        )

    chunk_repo = ChunkRepository(session)
    annotation_repo = AnnotationRepository(session)
    stats_repo = StatsRepository(session)

    try:
        timeline_view = KnowledgeGraphAuthorityService.from_session(session).build_timeline_view(run_id)
        timeline_plan = build_timeline_plan(
            run_id,
            chunk_repo,
            annotation_repo,
            stats_repo,
            timeline_view,
        )
    except TimelineDataUnavailableError:
        logger.warning("No chunks found for run {}", run_id)
        return TimelineResponse(
            meta=TimelineMeta(
                novel_id=novel_id,
                novel_name=novel_name,
                total_chunks=0,
            ),
            phases=[],
            composite_nodes=[],
            atomic_nodes=[],
            tension_curve=None,
        )

    api_composite_nodes = [
        TimelineCompositeNode.model_validate(serialize_timeline_composite_node(node))
        for node in timeline_plan.composite_nodes
    ]
    api_atomic_nodes = [
        TimelineNode.model_validate(serialize_timeline_node(node))
        for node in timeline_plan.atomic_nodes
    ]
    api_phases = [TimelinePhase.model_validate(item) for item in serialize_timeline_phases(timeline_plan.phases)]

    logger.info(
        "Timeline generated for novel {} task {}: {} composite nodes, {} atomic nodes, {} phases",
        novel_id,
        task_id,
        len(api_composite_nodes),
        len(api_atomic_nodes),
        len(api_phases),
    )

    return TimelineResponse(
        meta=TimelineMeta(
            novel_id=novel_id,
            novel_name=novel_name,
            total_chunks=timeline_plan.total_chunks,
        ),
        phases=api_phases,
        composite_nodes=api_composite_nodes,
        atomic_nodes=api_atomic_nodes,
        tension_curve=timeline_plan.tension_curve if include_curve else None,
    )
