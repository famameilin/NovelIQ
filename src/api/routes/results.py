"""
创建时间: 2026-03-11
创建者: Claude
任务: API 路由 - 结果导出
说明: 提供分析结果导出和查询接口

修改时间: 2026-03-14
修改者: TraeAI
任务: refactor-routes-use-repository
修改内容: 重构为使用 Repository 模式，所有路由添加 run_id 参数支持

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration
修改内容: 移除 has_db/get_db_path 等 SQLite 特有方法，使用单一 PostgreSQL 数据库

修改时间: 2026-03-28
修改者: TraeAI
任务: consolidate-codebase-architecture
修改内容: 使用 ResultsExportService 简化路由层

修改时间: 2026-03-30
修改者: CodeBuddy
任务: refactor-session-management
修改内容: 统一使用 FastAPI Depends 注入模式，删除手动 session 管理
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlalchemy.orm import Session

from src.api.dependencies import get_db_session, get_metrics_service, get_novel_service, resolve_run_id
from src.api.exceptions import AnalysisNotCompleteError, NovelNotFoundError
from src.api.models.responses import ResultsWriteResponse
from src.api.routes.results_fetchers import (
    _fetch_characters,
    _fetch_chunk_curves,
    _fetch_diagnosis,
    _fetch_graph_events_page,
    _fetch_graph_snapshot,
    _fetch_topics,
)
from src.api.services.metrics_service import MetricsService
from src.api.services.novel_service import NovelService
from src.api.services.results_export_service import fetch_all_results_data
from src.config import settings
from src.storage.repositories import (
    AnnotationRepository,
    ChunkRepository,
    RunRepository,
    StatsRepository,
)

router = APIRouter(prefix="/novels", tags=["results"])
GRAPH_PAGE_EVENT_LIMIT = 200


@router.get(
    "/{novel_id}/results",
    response_model=ResultsWriteResponse,
    summary="导出完整分析结果（复盘与测试用）",
    description="""
📋 **复盘与测试专用接口**

此接口将完整分析数据写入 `outputs/` 目录下的JSON文件，用于：
- 项目复盘与结果审查
- 测试验证与数据对比
- 分析结果归档备份

**参数：**
- task_id: 分析任务ID（8位短UUID，必需）

**返回内容：**
- 写入状态（成功/失败）
- 文件存储路径
- 数据完整性检查结果（缺失字段列表）

**生产环境数据获取请使用专用接口：**
- `GET /{novel_id}/chunk-curves` - 获取分块曲线（情绪 + 节奏）
- `GET /{novel_id}/characters` - 获取人物统计
- `GET /{novel_id}/topics` - 获取主题分布
- `GET /{novel_id}/diagnosis` - 获取云端诊断
- `GET /{novel_id}/metrics/*` - 获取各类聚合指标
""",
    responses={
        200: {
            "description": "结果已写入文件",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "分析结果已写入文件",
                        "file_path": "outputs/a1b2c3d4.json",
                        "novel_id": "10960c77",
                        "novel_name": "重明传",
                        "task_id": "a1b2c3d4",
                        "missing_fields": [],
                    }
                }
            },
        },
        400: {
            "description": "分析未完成或数据不完整",
            "content": {
                "application/json": {
                    "example": {
                        "success": False,
                        "message": "分析未完成，数据库不存在",
                        "file_path": None,
                        "novel_id": "10960c77",
                        "novel_name": None,
                        "task_id": "a1b2c3d4",
                        "missing_fields": ["chunk_curves"],
                    }
                }
            },
        },
    },
)
async def get_results(
    novel_id: str,
    task_id: Annotated[str, Query(..., description="分析任务ID")],
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
    novel_service: Annotated[NovelService, Depends(get_novel_service)],
) -> ResultsWriteResponse:
    """
    2026-03-12: Claude修改，检查任务状态是否为completed，如果任务未完成，抛出AnalysisNotCompleteError
    2026-03-13: TraeAI重构，提取数据获取和响应构建逻辑到独立函数
    2026-03-14: TraeAI重构，使用 Repository 模式
    2026-03-15: TraeAI重构，移除 has_db/get_db_path 等 SQLite 特有方法
    2026-03-17: TraeAI重构，将task_id改为run_id，使用完整UUID查询
    2026-03-19: TraeAI重构，将run_id参数改为task_id，内部转换为run_id
    2026-03-30: CodeBuddy重构，使用 Depends 注入 session
    """
    # run_id 已通过 resolve_run_id 依赖注入获取
    run_repo = RunRepository(session)
    run = run_repo.get_run(run_id)
    if not run:
        raise NovelNotFoundError(f"运行记录不存在: {run_id}")

    # 验证 run 是否属于该 novel
    if run.get("novel_id") != novel_id:
        # 使用 run_id 的前8位作为 task_id 确保错误消息准确
        actual_task_id = run_id[:8] if len(run_id) >= 8 else run_id
        raise NovelNotFoundError(f"任务 {actual_task_id} 不属于小说 {novel_id}")

    VALID_EXPORT_STATUSES = ("completed", "aggregated", "diagnosed")
    if run["status"] not in VALID_EXPORT_STATUSES:
        raise AnalysisNotCompleteError(f"分析未完成，当前状态: {run['status']}")

    stats_repo = StatsRepository(session)
    annotation_repo = AnnotationRepository(session)
    chunk_repo = ChunkRepository(session)

    results_data, missing_fields, novel_name = fetch_all_results_data(
        novel_id, task_id, run_id, stats_repo, annotation_repo, chunk_repo
    )

    file_path = _write_results_to_file(task_id, results_data)

    if missing_fields:
        logger.warning(f"Task {task_id} has missing fields: {missing_fields}")

    return _build_results_response(file_path, novel_id, novel_name, missing_fields)


def _build_results_response(
    file_path: str, novel_id: str, novel_name: str | None, missing_fields: list[str]
) -> ResultsWriteResponse:
    """
    2026-03-13: TraeAI创建，任务refactor-api-layer-functions
    构建结果响应对象
    """
    return ResultsWriteResponse(
        success=True,
        message="分析结果已写入文件",
        file_path=file_path,
        novel_id=novel_id,
        novel_name=novel_name,
        missing_fields=missing_fields if missing_fields else None,
    )


def _write_results_to_file(task_id: str, data: dict[str, Any]) -> str:
    results_dir = settings.paths.results_dir
    results_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{task_id}.json"
    file_path = results_dir / filename

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"Results written to {file_path}")
    return str(file_path)


@router.get("/{novel_id}/chunk-curves")
async def get_chunk_curves(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> list:
    """
    获取分块曲线数据（情绪 + 节奏）

    修改时间: 2026-04-21
    修改者: Codex
    任务: fuse-display-emotion-curve
    修改内容: 返回展示层融合后的单曲线结果，保持前端仍只消费一个 chunk_curves 接口
    """
    stats_repo = StatsRepository(session)
    annotation_repo = AnnotationRepository(session)
    chunk_repo = ChunkRepository(session)
    return _fetch_chunk_curves(run_id, stats_repo, annotation_repo, chunk_repo)


@router.get("/{novel_id}/characters")
async def get_characters(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> list:
    """
    获取角色统计数据

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: protagonist-score-fusion
    修改内容: 先获取 diagnosis，传递 arc_scores 和 main_characters 给 _fetch_characters
    """
    annotation_repo = AnnotationRepository(session)
    stats_repo = StatsRepository(session)

    alias_map = annotation_repo.fetch_alias_map(run_id)
    diagnosis = _fetch_diagnosis(run_id, novel_id, stats_repo, alias_map)

    arc_scores: dict[str, float] | None = None
    main_characters: list[str] | None = None
    if diagnosis:
        arc_scores = diagnosis.arc_scores if isinstance(diagnosis.arc_scores, dict) else None
        main_characters = diagnosis.main_characters

    return _fetch_characters(run_id, annotation_repo, arc_scores, main_characters)


@router.get("/{novel_id}/topics")
async def get_topics(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> list:
    """获取主题分布数据"""
    chunk_repo = ChunkRepository(session)
    annotation_repo = AnnotationRepository(session)
    alias_map = annotation_repo.fetch_alias_map(run_id)
    return _fetch_topics(run_id, chunk_repo, alias_map)


@router.get("/{novel_id}/diagnosis")
async def get_diagnosis(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> Any:
    """获取云端诊断数据"""
    stats_repo = StatsRepository(session)
    annotation_repo = AnnotationRepository(session)
    alias_map = annotation_repo.fetch_alias_map(run_id)
    return _fetch_diagnosis(run_id, novel_id, stats_repo, alias_map)


@router.get("/{novel_id}/graph")
async def get_graph(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict:
    """获取知识图谱快照"""
    annotation_repo = AnnotationRepository(session)
    return _fetch_graph_snapshot(run_id, annotation_repo)


@router.get("/{novel_id}/graph/events")
async def get_graph_events(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
    events_cursor: Annotated[str | None, Query(description="graph relation events 分页 cursor")] = None,
    events_limit: Annotated[int, Query(ge=1, le=GRAPH_PAGE_EVENT_LIMIT)] = GRAPH_PAGE_EVENT_LIMIT,
) -> dict:
    """获取 graph page relation events 的增量分页结果。"""
    annotation_repo = AnnotationRepository(session)
    try:
        return _fetch_graph_events_page(
            run_id,
            annotation_repo,
            events_cursor=events_cursor,
            events_limit=events_limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{novel_id}/metrics/narrative-structure")
async def get_narrative_structure(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
    metrics_service: Annotated[MetricsService, Depends(get_metrics_service)],
) -> Any:
    """获取叙事结构指标"""
    return metrics_service.get_narrative_structure(run_id, session)


@router.get("/{novel_id}/metrics/emotion-stats")
async def get_emotion_stats(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
    metrics_service: Annotated[MetricsService, Depends(get_metrics_service)],
) -> Any:
    """获取情感统计指标"""
    return metrics_service.get_emotion_stats(run_id, session)


@router.get("/{novel_id}/metrics/character-stats")
async def get_character_stats(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
    metrics_service: Annotated[MetricsService, Depends(get_metrics_service)],
) -> Any:
    """获取角色统计指标"""
    return metrics_service.get_character_stats(run_id, session)


@router.get("/{novel_id}/metrics/style-stats")
async def get_style_stats(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
    metrics_service: Annotated[MetricsService, Depends(get_metrics_service)],
) -> Any:
    """获取风格统计指标"""
    return metrics_service.get_style_stats(run_id, session)

