"""
说明: 提供分析结果导出和查询接口
"""

from __future__ import annotations

import json
from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlalchemy.orm import Session

from src.api.dependencies import (
    get_db_session,
    get_metrics_service,
    get_novel_service,
    resolve_run_id,
)
from src.api.exceptions import AnalysisNotCompleteError, DiagnosisRerunRequiredError, NovelNotFoundError
from src.api.models.responses import (
    CharacterStats,
    DiagnosisResult,
    ForeshadowingThreadResponse,
    ResultsWriteResponse,
)
from src.api.models.responses import (
    ChunkAnnotation as ChunkAnnotationResponse,
)
from src.api.routes.results_fetchers import (
    _fetch_characters,
    _fetch_chunk_annotations,
    _fetch_chunk_curves,
    _fetch_diagnosis,
    _fetch_foreshadowing_threads,
    _fetch_graph_events_page,
    _fetch_graph_snapshot,
    _fetch_topics,
)
from src.api.services.metrics_service import MetricsService
from src.api.services.novel_service import NovelService
from src.api.services.results_export_service import fetch_all_results_data
from src.api.services.results_queries.diagnosis import _is_complete_diagnosis_result
from src.config import settings
from src.storage.repositories import (
    AnnotationRepository,
    ChunkRepository,
    RunRepository,
    StatsRepository,
)

router = APIRouter(prefix="/novels", tags=["results"])
GRAPH_PAGE_EVENT_LIMIT = 200
READABLE_RUN_STATUSES = ("completed", "aggregated", "diagnosed")


def _require_run_for_novel(session: Session, novel_id: str, run_id: str) -> dict[str, Any]:
    """
    校验 run_id 存在且属于当前小说
    """
    run_repo = RunRepository(session)
    run = run_repo.get_run(run_id)
    if not run:
        raise NovelNotFoundError(novel_id=novel_id, message=f"运行记录不存在: {run_id}")

    if run.get("novel_id") != novel_id:
        actual_task_id = run_id[:8] if len(run_id) >= 8 else run_id
        raise NovelNotFoundError(
            novel_id=novel_id,
            message=f"任务 {actual_task_id} 不属于小说 {novel_id}",
        )

    return run


def _require_readable_run_status(run: dict[str, Any]) -> None:
    if run["status"] not in READABLE_RUN_STATUSES:
        raise AnalysisNotCompleteError(f"分析未完成，当前状态: {run['status']}")


def _raise_rerun_required_for_focus_contract(diagnosis: DiagnosisResult) -> NoReturn:
    """
    说明: 当前分支已经明确不兼容旧 diagnosis 合同；
    只要结果读取命中 rerun-required diagnosis，就应在 API 层显式中止，
    不能继续把旧 run 包装成“成功但无焦点数据”的静默降级结果
    修改时间: 2026-04-30
    修改原因: 明确该 helper 永不返回，避免路由层把 rerun-required 分支继续当成可达路径。
    """
    raise HTTPException(
        status_code=409,
        detail={
            "code": "diagnosis_rerun_required",
            "message": "当前任务的 diagnosis 焦点合同已失效，请重新分析。",
            "reason": diagnosis.rerun_reason,
        },
    )


def _fetch_and_require_valid_diagnosis(
    *,
    run_id: str,
    novel_id: str,
    stats_repo: StatsRepository,
    annotation_repo: AnnotationRepository,
    alias_map: dict[str, str] | None = None,
) -> DiagnosisResult:
    """
    说明: 部分结果接口虽然不直接返回 diagnosis，但它们的页面语义已经依赖
    新焦点合同是否有效；这里统一在路由层短路旧 run，避免不同页面对同一 run
    同时出现“需要重跑”和“还能继续看”的分裂状态
    修改时间: 2026-04-30
    修改原因: 显式把 rerun-required 分支收窄为不可返回路径，保证调用方拿到的一定是可读 diagnosis。
    """
    diagnosis = _fetch_diagnosis(
        run_id,
        novel_id,
        stats_repo,
        annotation_repo,
        alias_map,
    )
    if diagnosis is None:
        _raise_rerun_required_for_focus_contract(
            DiagnosisResult(
                rerun_required=True,
                rerun_reason="diagnosis_missing_focus_contract",
            )
        )
    if diagnosis.rerun_required:
        _raise_rerun_required_for_focus_contract(diagnosis)
    return diagnosis


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
- `GET /{novel_id}/chunk-annotations` - 获取分块标注与伏笔详情
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
    run = _require_run_for_novel(session, novel_id, run_id)

    _require_readable_run_status(run)

    stats_repo = StatsRepository(session)
    annotation_repo = AnnotationRepository(session)
    chunk_repo = ChunkRepository(session)

    try:
        results_data, missing_fields, novel_name = fetch_all_results_data(
            novel_id, task_id, run_id, stats_repo, annotation_repo, chunk_repo
        )
    except DiagnosisRerunRequiredError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "diagnosis_rerun_required",
                "message": "当前任务的 diagnosis 焦点合同已失效，请重新分析。",
                "reason": exc.reason,
            },
        ) from exc

    file_path = _write_results_to_file(task_id, results_data)

    if missing_fields:
        logger.warning(f"Task {task_id} has missing fields: {missing_fields}")

    return _build_results_response(file_path, novel_id, novel_name, missing_fields)


def _build_results_response(
    file_path: str, novel_id: str, novel_name: str | None, missing_fields: list[str]
) -> ResultsWriteResponse:
    """
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
    """
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    stats_repo = StatsRepository(session)
    annotation_repo = AnnotationRepository(session)
    chunk_repo = ChunkRepository(session)
    return _fetch_chunk_curves(run_id, stats_repo, annotation_repo, chunk_repo)


@router.get(
    "/{novel_id}/chunk-annotations",
    response_model=list[ChunkAnnotationResponse],
)
async def get_chunk_annotations(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[ChunkAnnotationResponse]:
    """
    获取分块标注与伏笔详情数据
    """
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    annotation_repo = AnnotationRepository(session)
    alias_map = annotation_repo.fetch_alias_map(run_id)
    return _fetch_chunk_annotations(
        run_id,
        annotation_repo,
        alias_map,
        require_graph_projection=False,
    )


@router.get("/{novel_id}/characters", response_model=list[CharacterStats])
async def get_characters(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> list:
    """
    获取角色统计数据
    """
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    annotation_repo = AnnotationRepository(session)
    stats_repo = StatsRepository(session)

    alias_map = annotation_repo.fetch_alias_map(run_id)
    diagnosis = _fetch_diagnosis(run_id, novel_id, stats_repo, annotation_repo, alias_map)
    if diagnosis is not None and diagnosis.rerun_required:
        _raise_rerun_required_for_focus_contract(diagnosis)

    arc_scores: dict[str, float] | None = None
    focus_characters: list[str] | None = None
    main_characters: list[str] | None = None
    if _is_complete_diagnosis_result(diagnosis):
        arc_scores = diagnosis.arc_scores
        focus_characters = diagnosis.focus_characters
        main_characters = diagnosis.main_characters

    return _fetch_characters(run_id, annotation_repo, arc_scores, focus_characters, main_characters, limit=None)


@router.get("/{novel_id}/topics")
async def get_topics(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> list:
    """获取主题分布数据"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    chunk_repo = ChunkRepository(session)
    annotation_repo = AnnotationRepository(session)
    alias_map = annotation_repo.fetch_alias_map(run_id)
    stats_repo = StatsRepository(session)
    _fetch_and_require_valid_diagnosis(
        run_id=run_id,
        novel_id=novel_id,
        stats_repo=stats_repo,
        annotation_repo=annotation_repo,
        alias_map=alias_map,
    )
    return _fetch_topics(run_id, chunk_repo, alias_map)


@router.get("/{novel_id}/diagnosis", response_model=DiagnosisResult)
async def get_diagnosis(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> DiagnosisResult:
    """
    获取诊断数据

    修改时间: 2026-04-30
    修改原因: diagnosis 查询链路对外声明始终返回 DiagnosisResult；
              读取层即使出现意外空值，也要在路由层回退到 rerun-required 结果而不是泄漏 None。
    """
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    stats_repo = StatsRepository(session)
    annotation_repo = AnnotationRepository(session)
    alias_map = annotation_repo.fetch_alias_map(run_id)
    diagnosis = _fetch_diagnosis(run_id, novel_id, stats_repo, annotation_repo, alias_map)
    if diagnosis is None:
        return DiagnosisResult(
            rerun_required=True,
            rerun_reason="diagnosis_missing_focus_contract",
        )
    return diagnosis


@router.get(
    "/{novel_id}/foreshadowing-threads",
    response_model=list[ForeshadowingThreadResponse],
)
async def get_foreshadowing_threads(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[ForeshadowingThreadResponse]:
    """
    获取跨 chunk 的 setup thread 台账

    说明: 返回 full setup ledger + active 状态，供 diagnosis drill-down 与导出复用
    """
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    annotation_repo = AnnotationRepository(session)
    return _fetch_foreshadowing_threads(run_id, annotation_repo)


@router.get("/{novel_id}/graph")
async def get_graph(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict:
    """
    获取知识图谱快照
    """
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    annotation_repo = AnnotationRepository(session)
    alias_map = annotation_repo.fetch_alias_map(run_id)
    stats_repo = StatsRepository(session)
    _fetch_and_require_valid_diagnosis(
        run_id=run_id,
        novel_id=novel_id,
        stats_repo=stats_repo,
        annotation_repo=annotation_repo,
        alias_map=alias_map,
    )
    return _fetch_graph_snapshot(run_id, annotation_repo)


@router.get("/{novel_id}/graph/events")
async def get_graph_events(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
    events_cursor: Annotated[str | None, Query(description="graph relation events 分页 cursor")] = None,
    events_limit: Annotated[int, Query(ge=1, le=GRAPH_PAGE_EVENT_LIMIT)] = GRAPH_PAGE_EVENT_LIMIT,
) -> dict:
    """
    获取 graph page relation events 的增量分页结果
    """
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    annotation_repo = AnnotationRepository(session)
    alias_map = annotation_repo.fetch_alias_map(run_id)
    stats_repo = StatsRepository(session)
    _fetch_and_require_valid_diagnosis(
        run_id=run_id,
        novel_id=novel_id,
        stats_repo=stats_repo,
        annotation_repo=annotation_repo,
        alias_map=alias_map,
    )
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
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    return metrics_service.get_narrative_structure(run_id, session)


@router.get("/{novel_id}/metrics/emotion-stats")
async def get_emotion_stats(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
    metrics_service: Annotated[MetricsService, Depends(get_metrics_service)],
) -> Any:
    """获取情感统计指标"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    return metrics_service.get_emotion_stats(run_id, session)


@router.get("/{novel_id}/metrics/character-stats")
async def get_character_stats(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
    metrics_service: Annotated[MetricsService, Depends(get_metrics_service)],
) -> Any:
    """获取角色统计指标"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    return metrics_service.get_character_stats(run_id, session)


@router.get("/{novel_id}/metrics/style-stats")
async def get_style_stats(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
    metrics_service: Annotated[MetricsService, Depends(get_metrics_service)],
) -> Any:
    """获取风格统计指标"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    return metrics_service.get_style_stats(run_id, session)
