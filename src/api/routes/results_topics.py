"""
主题与诊断结果查询路由

说明: 从 src/api/routes/results.py 拆出主题族路由（topics/aggregate/series/shifts/emotion）
与诊断、伏笔树路由（diagnosis/foreshadowing-trees），行为保持不变。
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.api.models.responses import (
    ChapterTopicAggregateResponse,
    DiagnosisResult,
    ForeshadowingTreeResponse,
    TopicAggregateResponse,
    TopicEmotionResponse,
    TopicSeriesResponse,
    TopicShiftConfig,
    TopicShiftResponse,
)
from src.api.routes.results_common import (
    _require_readable_run_status,
    _require_run_for_novel,
    get_db_session,
    resolve_run_id,
)
from src.api.services.results_queries import (
    _fetch_diagnosis,
    _fetch_foreshadowing_trees,
    _fetch_topics,
)
from src.metrics.aggregate.algorithms import compute_topic_shift_candidates
from src.metrics.aggregate.topic_aggregations import (
    aggregate_book_topics,
    aggregate_chapter_topics,
    compute_topic_emotion,
    fetch_paragraph_topic_series,
)
from src.storage.repositories import AnnotationRepository, ParagraphRepository, StatsRepository

# 说明: tags 由主模块 router（tags=["results"]）在 include 时统一附加，避免标签重复
router = APIRouter()


@router.get("/{novel_id}/topics")
async def get_topics(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> list:
    """获取主题分布数据（段落 token 加权聚合，§11.1）"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    paragraph_repo = ParagraphRepository(session)
    return _fetch_topics(run_id, paragraph_repo)


@router.get("/{novel_id}/topics/aggregate", response_model=TopicAggregateResponse | ChapterTopicAggregateResponse)
async def get_topic_aggregate(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
    level: Literal["book", "chapter"] = Query(default="book", description="聚合层级：book 或 chapter"),
) -> TopicAggregateResponse | ChapterTopicAggregateResponse:
    """
    全书/章节主题分布（§5.11 D1）：token 加权聚合，分母从每段一行推断状态读取

    章节层级按 chapters.sequence 排序；缺失或样本不足返回 unavailable_reason。
    """
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    if level == "chapter":
        return ChapterTopicAggregateResponse(**aggregate_chapter_topics(run_id, session))
    return TopicAggregateResponse(**aggregate_book_topics(run_id, session))


@router.get("/{novel_id}/topics/series", response_model=TopicSeriesResponse)
async def get_topic_series(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> TopicSeriesResponse:
    """
    段落主题序列（D1）：完整 K 维权重，横轴真实字符位置（global_start_char）

    top_n 只属于前端展示裁剪，本接口始终返回完整分布。
    """
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    return TopicSeriesResponse(**fetch_paragraph_topic_series(run_id, session))


@router.get("/{novel_id}/topics/shifts", response_model=TopicShiftResponse)
async def get_topic_shifts(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
    window_size: Annotated[
        int | None, Query(ge=1, description="窗口段落数，缺省取 topic_shift 配置")
    ] = None,
    min_tokens_per_window: Annotated[
        int | None, Query(ge=1, description="窗口最小实际入模 token 数，缺省取配置")
    ] = None,
    score_threshold: Annotated[
        float | None, Query(gt=0, le=1, description="候选点 JS 散度阈值，缺省取配置")
    ] = None,
    max_candidates: Annotated[
        int | None, Query(ge=1, description="候选点数量上限，缺省取配置")
    ] = None,
) -> TopicShiftResponse:
    """
    主题变化候选点（D2）：相邻不重叠窗口分布（入模 token 加权）的 JS 散度

    topic_shift_score 为以 2 为底、范围 [0,1] 的 JS 散度；窗口大小、最小
    token 数与阈值均为版本化配置（返回在 config 中），本端点允许显式覆盖
    用于探索。候选点不直接命名"情节转折点"，须与 Agent 事件和人工样本
    联合验证。
    """
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    series = fetch_paragraph_topic_series(run_id, session)
    if series["unavailable_reason"]:
        from src.config import settings as _settings

        shift_settings = _settings.topic_model.topic_shift
        return TopicShiftResponse(
            candidates=[],
            config=TopicShiftConfig(
                window_size=window_size if window_size is not None else shift_settings.window_size,
                min_tokens_per_window=(
                    min_tokens_per_window
                    if min_tokens_per_window is not None
                    else shift_settings.min_tokens_per_window
                ),
                score_threshold=(
                    score_threshold if score_threshold is not None else shift_settings.score_threshold
                ),
                max_candidates=(
                    max_candidates if max_candidates is not None else shift_settings.max_candidates
                ),
            ),
            unavailable_reason=series["unavailable_reason"],
        )
    return TopicShiftResponse(
        **compute_topic_shift_candidates(
            series,
            window_size=window_size,
            min_tokens_per_window=min_tokens_per_window,
            score_threshold=score_threshold,
            max_candidates=max_candidates,
        )
    )


@router.get("/{novel_id}/topics/emotion", response_model=TopicEmotionResponse)
async def get_topic_emotion(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> TopicEmotionResponse:
    """
    主题-情感统计（D3）：sum(weight * token * net_density) / sum(weight * token)

    情感输入使用 paragraph_curves.net_density 原始值；空值段落同时从
    分子分母排除；权重和为零时返回空值与原因。
    """
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    return TopicEmotionResponse(**compute_topic_emotion(run_id, session))


@router.get("/{novel_id}/diagnosis", response_model=DiagnosisResult)
async def get_diagnosis(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> DiagnosisResult:
    """
    获取诊断数据

    缺少诊断记录时返回当前响应模型的空值字段
    """
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    stats_repo = StatsRepository(session)
    diagnosis = _fetch_diagnosis(run_id, novel_id, stats_repo)
    return diagnosis or DiagnosisResult()


@router.get(
    "/{novel_id}/foreshadowing-trees",
    response_model=list[ForeshadowingTreeResponse],
)
async def get_foreshadowing_trees(
    novel_id: str,
    run_id: Annotated[str, Depends(resolve_run_id)],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[ForeshadowingTreeResponse]:
    """
    获取伏笔树台账（2026-09-13 伏笔即事件树）

    说明: 返回全部伏笔树 + active 状态，供 diagnosis drill-down 与导出复用
    """
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    annotation_repo = AnnotationRepository(session)
    return _fetch_foreshadowing_trees(run_id, annotation_repo)
