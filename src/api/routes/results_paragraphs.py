"""段落级结果查询路由"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from src.api.models.responses import (
    ChapterAnnotation as ChapterAnnotationResponse,
)
from src.api.models.responses import (
    ChapterMetricsResponse,
    CharacterStats,
    EmotionTrendWindow,
    ParagraphCurvePoint,
)
from src.api.routes.results_common import (
    _parse_emotion_trend_range,
    _require_readable_run_status,
    _require_run_for_novel,
    get_db_session,
    resolve_run_id,
)
from src.api.services.results_queries import (
    _fetch_chapter_annotations,
    _fetch_characters,
    _fetch_diagnosis,
)
from src.api.services.results_queries.diagnosis import _has_diagnosis_result
from src.api.services.results_queries.paragraphs import (
    _fetch_chapter_metrics,
    _fetch_emotion_trend,
    _fetch_paragraph_curves,
)
from src.storage.repositories import AnnotationRepository, ParagraphRepository, StatsRepository

# tags 由主模块 router（tags=["results"]）在 include 时统一附加，避免标签重复
router = APIRouter()


@router.get(
    "/{novel_id}/paragraph-curves",
    response_model=list[ParagraphCurvePoint],
    summary="段落曲线（展示降采样可选）",
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
    paragraph_repo = ParagraphRepository(session)
    return _fetch_paragraph_curves(run_id, paragraph_repo, max_points)


@router.get(
    "/{novel_id}/emotion-trend",
    response_model=list[EmotionTrendWindow],
    summary="情绪趋势窗口聚合（缩放自适应窗口）",
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
    获取情绪趋势窗口聚合序列（展示层重采样，不回写数据库）

    每窗段落数作用于 range 过滤后的段落集；窗口大小由服务端钳制到 5~40。
    """
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    range_values = request.query_params.getlist("range")
    parsed_range = _parse_emotion_trend_range(",".join(range_values) if len(range_values) > 1 else position_range)
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
    summary="章节与全书汇总指标",
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
    arc_scores: dict[str, float] | None = None
    focus_characters: list[str] | None = None
    main_characters: list[str] | None = None
    if diagnosis is not None and _has_diagnosis_result(diagnosis):
        arc_scores = diagnosis.arc_scores
        focus_characters = diagnosis.focus_characters
        main_characters = diagnosis.main_characters

    return _fetch_characters(run_id, annotation_repo, arc_scores, focus_characters, main_characters, limit=None)
