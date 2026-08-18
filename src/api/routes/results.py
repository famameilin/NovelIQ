"""
说明: 提供分析结果导出和查询接口
"""

from __future__ import annotations

import json
import math
from typing import Annotated, Any, Literal, NoReturn, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from loguru import logger
from sqlalchemy.orm import Session

from src.api.contract_guards import require_paragraph_contract
from src.api.dependencies import (
    get_db_session,
    get_metrics_service,
    get_novel_service,
    resolve_run_id,
)
from src.api.exceptions import AnalysisNotCompleteError, DiagnosisRerunRequiredError, NovelNotFoundError
from src.api.models.event_forest import (
    EventChapterRootResponse,
    EventEdgeResponse,
    EventForestResponse,
    EventNodeResponse,
    ForeshadowingEdgeResponse,
)
from src.api.models.graph import GraphChangesResponse, GraphSnapshotResponse
from src.api.models.responses import (
    ChapterAnnotation as ChapterAnnotationResponse,
)
from src.api.models.responses import (
    ChapterMetricsResponse,
    CharacterStats,
    DiagnosisResult,
    EmotionTrendWindow,
    ForeshadowingThreadResponse,
    GlobalStats,
    ParagraphCurvePoint,
    ResultsWriteResponse,
)
from src.api.routes.results_fetchers import (
    _fetch_chapter_annotations,
    _fetch_characters,
    _fetch_diagnosis,
    _fetch_foreshadowing_threads,
    _fetch_graph_changes_page,
    _fetch_graph_snapshot,
    _fetch_topics,
)
from src.api.services.metrics_service import MetricsService
from src.api.services.novel_service import NovelService
from src.api.services.results_export_service import fetch_all_results_data
from src.api.services.results_queries.diagnosis import _is_complete_diagnosis_result
from src.api.services.results_queries.graph import GRAPH_CHANGE_LIMIT
from src.api.services.results_queries.paragraphs import (
    _fetch_chapter_metrics,
    _fetch_emotion_trend,
    _fetch_paragraph_curves,
)
from src.config import settings
from src.storage.repositories import (
    AnnotationRepository,
    ChapterRepository,
    ParagraphRepository,
    RunRepository,
    StatsRepository,
)

router = APIRouter(prefix="/novels", tags=["results"])
# 2026-08-14 D3：新管线只写 completed/running/pending/failed/cancelling/cancelled，
# aggregated/diagnosed 是旧合同状态，不再视为可读；无图 run 由图就绪 409 兜底
# （GraphReadinessError），状态可读与数据可读在此对齐
READABLE_RUN_STATUSES = ("completed",)


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
        raise AnalysisNotCompleteError(
            f"分析未完成，当前状态: {run['status']}",
            run_status=run["status"],
        )


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


def _parse_emotion_trend_range(
    position_range: str | None,
) -> tuple[float, float] | None:
    """2026-08-15 解析情绪趋势 position 区间并统一校验输入"""
    if position_range is None:
        return None
    raw = position_range.strip()
    try:
        values = (
            json.loads(raw)
            if raw.startswith("[")
            else [part.strip() for part in raw.split(",")]
        )
        if not isinstance(values, list) or len(values) != 2:
            raise ValueError
        start, end = float(values[0]), float(values[1])
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=422,
            detail="range 格式必须为 start,end 或 [start,end]",
        ) from exc

    if not all(math.isfinite(value) and 0 <= value <= 1 for value in (start, end)):
        raise HTTPException(status_code=422, detail="range 的 position 必须位于 0~1")
    if start >= end:
        raise HTTPException(status_code=422, detail="range 起点必须小于终点")
    return start, end


def _fetch_and_require_valid_diagnosis(
    *,
    run_id: str,
    novel_id: str,
    stats_repo: StatsRepository,
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
- `GET /{novel_id}/paragraph-curves` - 获取段落曲线（情绪 + 张力）
- `GET /{novel_id}/chapter-annotations` - 获取分块标注与伏笔详情
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
                        "missing_fields": ["paragraph_curves"],
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
    require_paragraph_contract(run)

    stats_repo = StatsRepository(session)
    annotation_repo = AnnotationRepository(session)
    chapter_repo = ChapterRepository(session)

    try:
        results_data, missing_fields, novel_name = fetch_all_results_data(
            novel_id, task_id, run_id, stats_repo, annotation_repo, chapter_repo
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


@router.get(
    "/{novel_id}/paragraph-curves",
    response_model=list[ParagraphCurvePoint],
    summary="段落曲线（§13.1，展示降采样可选）",
)
async def get_paragraph_curves(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
    max_points: Annotated[int | None, Query(gt=0, description="展示降采样点数上限")] = None,
) -> list[ParagraphCurvePoint]:
    """
    获取段落曲线（完整曲线始终一段一点，max_points 仅降采样响应，不回写数据库）

    章节边界段落与 net_density 全局峰值在降采样时强制保留。
    """
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    require_paragraph_contract(run)
    paragraph_repo = ParagraphRepository(session)
    return _fetch_paragraph_curves(run_id, paragraph_repo, max_points)


@router.get(
    "/{novel_id}/emotion-trend",
    response_model=list[EmotionTrendWindow],
    summary="情绪趋势窗口聚合（§13.1 展示层，缩放自适应窗口）",
)
async def get_emotion_trend(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    position_range: Annotated[
        str | None,
        Query(alias="range", description="position 区间，格式为 start,end，取值 0~1"),
    ] = None,
    window_paragraphs: Annotated[int, Query(description="目标窗口大小，服务端钳制到 5~40")] = 20,
) -> list[EmotionTrendWindow]:
    """
    2026-08-15 提供按 position 区间和每窗段落数重聚合的情绪趋势数据

    获取情绪趋势窗口聚合序列（展示层重采样，不回写数据库）

    每窗段落数作用于 range 过滤后的段落集；窗口大小由服务端钳制到 5~40，
    深缩放段数不足时最后一个窗口自然退化为实际剩余段落数。
    """
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    require_paragraph_contract(run)
    range_values = request.query_params.getlist("range")
    parsed_range = _parse_emotion_trend_range(
        ",".join(range_values) if len(range_values) > 1 else position_range
    )
    paragraph_repo = ParagraphRepository(session)
    return _fetch_emotion_trend(
        run_id,
        paragraph_repo,
        parsed_range[0] if parsed_range else None,
        parsed_range[1] if parsed_range else None,
        window_paragraphs,
    )


@router.get(
    "/{novel_id}/chapter-metrics",
    response_model=ChapterMetricsResponse,
    summary="章节与全书汇总指标（§13.2）",
)
async def get_chapter_metrics(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ChapterMetricsResponse:
    """
    获取由段落充分统计量聚合的章节汇总与全书聚合（分子/分母守恒，禁止等权平均）
    """
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    require_paragraph_contract(run)
    paragraph_repo = ParagraphRepository(session)
    annotation_repo = AnnotationRepository(session)
    return _fetch_chapter_metrics(run_id, paragraph_repo, annotation_repo, run)


@router.get(
    "/{novel_id}/chapter-annotations",
    response_model=list[ChapterAnnotationResponse],
)
async def get_chapter_annotations(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[ChapterAnnotationResponse]:
    """
    获取分块标注与伏笔详情数据
    """
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    annotation_repo = AnnotationRepository(session)
    return _fetch_chapter_annotations(
        run_id,
        annotation_repo,
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

    diagnosis = _fetch_diagnosis(run_id, novel_id, stats_repo)
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
    """获取主题分布数据（段落 token 加权聚合，§11.1）"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    # 2026-08-15 M6：/topics 数据源已切换为 paragraph_topics，与 /paragraph-curves、
    # /chapter-metrics 同口径要求段落合同；旧 run 无段落主题数据时 409 而非静默空数组
    require_paragraph_contract(run)
    paragraph_repo = ParagraphRepository(session)
    stats_repo = StatsRepository(session)
    _fetch_and_require_valid_diagnosis(
        run_id=run_id,
        novel_id=novel_id,
        stats_repo=stats_repo,
    )
    return _fetch_topics(run_id, paragraph_repo)


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
    diagnosis = _fetch_diagnosis(run_id, novel_id, stats_repo)
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


@router.get("/{novel_id}/graph", response_model=GraphSnapshotResponse)
async def get_graph(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
    chapter_id: Annotated[int | None, Query(gt=0)] = None,
    graph_version_id: Annotated[str | None, Query(min_length=1)] = None,
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
            graph_version_id=graph_version_id,
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


@router.get("/{novel_id}/metrics/global-stats", response_model=GlobalStats)
async def get_global_stats(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> GlobalStats:
    """
    说明: 提供详情概览使用的全书波动统计查询
    修改时间: 2026-08-16
    修改原因: 前端需要直接读取已持久化的 global_stats，避免通过导出文件反查
    """
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    stats_repo = StatsRepository(session)
    chapter_repo = ChapterRepository(session)
    from src.api.services.results_queries.metadata import _fetch_global_stats

    stats = _fetch_global_stats(run_id, stats_repo, chapter_repo)
    return stats or GlobalStats()


@router.get("/{novel_id}/event-forest", response_model=EventForestResponse)
async def get_event_forest(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
    chapter_id: Annotated[int | None, Query(gt=0)] = None,
    graph_version_id: Annotated[str | None, Query(min_length=1)] = None,
) -> EventForestResponse:
    """
    说明: 提供事件森林/DAG 查询，返回章节根、事件节点、三类边、锚点、Evidence、可见边界和派生顺序
    修改时间: 2026-08-18
    修改原因: P2 事件过程层正式接管，新增事件森林 API 交付项
    """
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    require_paragraph_contract(run)
    from src.storage.repositories.graph import EventForestRepository

    repo = EventForestRepository(session)
    try:
        snapshot = repo.fetch_snapshot(
            run_id,
            chapter_id=chapter_id,
            graph_version_id=graph_version_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail="当前 run 尚无匹配的章节图版本",
        )
    return EventForestResponse(
        graph_version_id=snapshot.graph_version_id,
        chapter_order=snapshot.chapter_order,
        visible_through_chapter_order=snapshot.visible_through_chapter_order,
        chapter_roots=[
            EventChapterRootResponse(
                chapter_id=root.chapter_id,
                chapter_order=root.chapter_order,
                event_ids=root.event_ids,
            )
            for root in snapshot.chapter_roots
        ],
        derived_event_order=snapshot.derived_event_order,
        event_nodes=[
            EventNodeResponse(
                event_id=node.event_id,
                event_revision=node.event_revision,
                chapter_id=node.chapter_id,
                chapter_order=node.chapter_order,
                description=node.description,
                participants=node.participants,
                anchor_paragraph_ids=node.anchor_paragraph_ids,
                char_start=node.char_start,
                char_end=node.char_end,
                text_hash=node.text_hash,
                evidence=node.evidence,
                causal_event_refs=node.causal_event_refs,
            )
            for node in snapshot.event_nodes
        ],
        event_edges=[
            EventEdgeResponse(
                edge_id=edge.edge_id,
                edge_type=cast(Literal["contains", "causal"], edge.edge_type),
                source_event_id=edge.source_event_id,
                source_event_revision=edge.source_event_revision,
                target_event_id=edge.target_event_id,
                target_event_revision=edge.target_event_revision,
                source_chapter_id=edge.source_chapter_id,
                target_chapter_id=edge.target_chapter_id,
                is_active=edge.is_active,
                evidence=edge.evidence,
            )
            for edge in snapshot.event_edges
        ],
        foreshadowing_edges=[
            ForeshadowingEdgeResponse(
                setup_id=fe.setup_id,
                setup_event_id=fe.setup_event_id,
                payoff_event_id=fe.payoff_event_id,
                first_chapter_id=fe.first_chapter_id,
                last_chapter_id=fe.last_chapter_id,
                setup_summary=fe.setup_summary,
                status=fe.status,
                active=fe.active,
            )
            for fe in snapshot.foreshadowing_edges
        ],
    )
