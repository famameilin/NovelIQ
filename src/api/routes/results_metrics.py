"""
聚合指标结果查询路由

说明: 从 src/api/routes/results.py 拆出 metrics/* 域路由（叙事结构/情感/角色/风格/全书波动），
行为保持不变。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.api.dependencies import get_metrics_service
from src.api.models.responses import GlobalStats
from src.api.routes.results_common import (
    _require_readable_run_status,
    _require_run_for_novel,
    get_db_session,
    resolve_run_id,
)
from src.api.services.metrics_service import MetricsService
from src.storage.repositories import ChapterRepository, StatsRepository

# 说明: tags 由主模块 router（tags=["results"]）在 include 时统一附加，避免标签重复
router = APIRouter()


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
    """查询详情概览使用的全书波动统计"""
    run = _require_run_for_novel(session, novel_id, run_id)
    _require_readable_run_status(run)
    stats_repo = StatsRepository(session)
    chapter_repo = ChapterRepository(session)
    from src.api.services.results_queries.metadata import _fetch_global_stats

    stats = _fetch_global_stats(run_id, stats_repo, chapter_repo)
    return stats or GlobalStats()
