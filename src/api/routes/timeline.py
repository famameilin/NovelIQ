"""
叙事时间轴 API 路由

创建时间: 2026-03-30
创建者: CodeBuddy
任务: 实现叙事时间轴功能
说明: 提供时间轴数据查询接口，支持四阶段划分、节点筛选和张力曲线

修改时间: 2026-03-30
修改者: CodeBuddy
任务: refactor-session-management
修改内容: 添加 DTO 到 Pydantic 模型的转换函数，适配 metrics 层 DTO
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from loguru import logger
from sqlalchemy.orm import Session

from src.api.dependencies import get_db_session
from src.api.exceptions import AnalysisNotCompleteError, NovelNotFoundError
from src.api.models.responses import ErrorResponse
from src.api.models.timeline import (
    RelationChangeEvent,
    TimelineMeta,
    TimelineNode,
    TimelinePhase,
    TimelineResponse,
)
from src.api.routes.novels import get_novel_service
from src.api.services.novel_service import NovelService
from src.metrics.timeline_metrics import (
    TimelineNodeDTO,
    TimelinePhaseDTO,
    RelationChangeEventDTO,
    build_timeline_candidates,
    convert_to_timeline_nodes,
    select_timeline_nodes,
)
from src.storage.repositories import (
    AnnotationRepository,
    ChunkRepository,
    RunRepository,
    StatsRepository,
)

router = APIRouter(prefix="/novels", tags=["timeline"])


def _dto_to_relation_change_event(dto: RelationChangeEventDTO) -> RelationChangeEvent:
    """将 RelationChangeEventDTO 转换为 Pydantic 模型"""
    return RelationChangeEvent(
        from_char=dto.from_char,
        to_char=dto.to_char,
        relation_type=dto.relation_type,
        change_type=dto.change_type,
        evidence=dto.evidence,
    )


def _dto_to_timeline_phase(dto: TimelinePhaseDTO) -> TimelinePhase:
    """将 TimelinePhaseDTO 转换为 Pydantic 模型"""
    return TimelinePhase(
        name=dto.name,
        start=dto.start,
        end=dto.end,
        ratio=dto.ratio,
    )


def _dto_to_timeline_node(dto: TimelineNodeDTO) -> TimelineNode:
    """将 TimelineNodeDTO 转换为 Pydantic 模型"""
    return TimelineNode(
        chunk_id=dto.chunk_id,
        progress=dto.progress,
        importance_score=dto.importance_score,
        level=dto.level,
        event=dto.event,
        characters=dto.characters,
        is_pivot=dto.is_pivot,
        is_cliffhanger=dto.is_cliffhanger,
        tension_percentile=dto.tension_percentile,
        node_type=dto.node_type,
        relation_changes=[
            _dto_to_relation_change_event(rc) for rc in dto.relation_changes
        ] if dto.relation_changes else None,
        character_entries=dto.character_entries,
        character_exits=dto.character_exits,
    )


@router.get(
    "/{novel_id}/timeline",
    response_model=TimelineResponse,
    summary="获取叙事时间轴",
    description="""
📊 **叙事时间轴接口**

基于张力曲线、知识图谱和标注数据，生成小说的时间轴视图。

**功能：**
- 四阶段划分（引入期/发展期/高潮期/收束期）
- 重要节点识别（转折点、悬念点、角色登场/退场、关系变化）
- 张力曲线数据

**参数：**
- task_id: 分析任务ID（必需）
- include_curve: 是否包含张力曲线数据（默认 false）
- max_level: 显示重要性级别 ≤ 此值的节点（默认 3，即显示全部）
  - 1: 仅重要节点
  - 2: 重要 + 较重要节点
  - 3: 全部节点

**返回：**
- meta: 时间轴元信息
- phases: 四阶段划分
- nodes: 时间轴节点列表
- tension_curve: 张力曲线数据（可选）
""",
    responses={
        200: {
            "description": "时间轴数据",
            "content": {
                "application/json": {
                    "example": {
                        "meta": {
                            "novel_id": "novel_001",
                            "novel_name": "重明传",
                            "total_chunks": 500,
                        },
                        "phases": [
                            {"name": "引入期", "start": 1, "end": 75, "ratio": 0.15},
                            {"name": "发展期", "start": 76, "end": 350, "ratio": 0.55},
                            {"name": "高潮期", "start": 351, "end": 420, "ratio": 0.14},
                            {"name": "收束期", "start": 421, "end": 500, "ratio": 0.16},
                        ],
                        "nodes": [
                            {
                                "chunk_id": 1,
                                "progress": 0.0,
                                "importance_score": 6.0,
                                "level": 1,
                                "event": "贺重明在宗门试炼中展露天赋",
                                "characters": ["贺重明", "长老"],
                                "is_pivot": False,
                                "is_cliffhanger": False,
                                "tension_percentile": 45,
                                "node_type": "character_entry",
                                "relation_changes": None,
                                "character_entries": ["贺重明"],
                                "character_exits": None,
                            }
                        ],
                        "tension_curve": None,
                    }
                }
            },
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
    task_id: Annotated[str, Query(..., description="分析任务ID（8位短UUID）")],
    include_curve: Annotated[bool, Query(False, description="是否包含张力曲线数据")],
    max_level: Annotated[int, Query(3, ge=1, le=3, description="显示重要性级别 ≤ 此值的节点")],
    session: Annotated[Session, Depends(get_db_session)],
    service: Annotated[NovelService, Depends(get_novel_service)],
) -> TimelineResponse:
    """获取叙事时间轴数据"""

    # 1. 验证小说存在
    novels = service.list_novels()
    novel_info = next((n for n in novels if n.get("novel_id") == novel_id), None)
    if novel_info is None:
        raise NovelNotFoundError(f"小说不存在: {novel_id}")

    novel_name = novel_info.get("filename", "未知")

    # 2. 获取 run_id (task_id 是 run_id 的前 8 位)
    run_repo = RunRepository(session)
    run_data = run_repo.get_run_by_run_id_prefix(task_id)
    if run_data is None:
        raise NovelNotFoundError(f"任务不存在: {task_id}")

    # 验证 run 是否属于该 novel
    if run_data.get("novel_id") != novel_id:
        raise NovelNotFoundError(f"任务 {task_id} 不属于小说 {novel_id}")

    run_id = run_data["run_id"]

    # 3. 检查分析是否完成
    if run_data["status"] not in ("completed", "aggregated", "diagnosed"):
        raise AnalysisNotCompleteError(f"分析尚未完成，当前状态: {run_data['status']}")

    # 4. 构建时间轴候选节点（共享函数）
    chunk_repo = ChunkRepository(session)
    annotation_repo = AnnotationRepository(session)
    stats_repo = StatsRepository(session)

    try:
        (
            candidates,
            tension_scores,
            chunk_ids,
            total_chunks,
            timeline_phases,
            major_character_entries,
            relation_break_events,
        ) = build_timeline_candidates(run_id, chunk_repo, annotation_repo, stats_repo)
    except ValueError:
        logger.warning(f"No chunks found for run {run_id}")
        return TimelineResponse(
            meta=TimelineMeta(
                novel_id=novel_id,
                novel_name=novel_name,
                total_chunks=0,
            ),
            phases=[],
            nodes=[],
            tension_curve=None,
        )

    # 5. 筛选节点
    selected_candidates = select_timeline_nodes(
        candidates=candidates,
        chunk_ids=chunk_ids,
        tension_scores=tension_scores,
        major_character_entries=major_character_entries,
        relation_break_events=relation_break_events,
        min_nodes=10,
        max_nodes=20,
    )

    # 6. 根据 max_level 过滤节点
    selected_candidates = [c for c in selected_candidates if c.level <= max_level]

    # 转换为 API 模型
    timeline_nodes = convert_to_timeline_nodes(selected_candidates)
    # DTO -> Pydantic 模型转换
    api_nodes = [_dto_to_timeline_node(node) for node in timeline_nodes]
    api_phases = [_dto_to_timeline_phase(phase) for phase in timeline_phases]

    logger.info(
        f"Timeline generated for novel {novel_id}, task {task_id}: "
        f"{len(api_nodes)} nodes, {len(api_phases)} phases"
    )

    return TimelineResponse(
        meta=TimelineMeta(
            novel_id=novel_id,
            novel_name=novel_name,
            total_chunks=total_chunks,
        ),
        phases=api_phases,
        nodes=api_nodes,
        tension_curve=tension_scores if include_curve else None,
    )
