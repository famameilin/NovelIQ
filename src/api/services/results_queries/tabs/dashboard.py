"""仪表盘与节奏张力 tab 组装"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from src.api.services.metrics_service import MetricsService
from src.api.services.results_queries.diagnosis import _fetch_diagnosis
from src.api.services.results_queries.paragraphs import (
    _fetch_chapter_metrics,
    _fetch_emotion_trend,
    _fetch_paragraph_curves,
)
from src.api.services.results_queries.topics import _fetch_topics
from src.storage.repositories import AnnotationRepository, ParagraphRepository, StatsRepository

_DASHBOARD_WINDOW_PARAGRAPHS = 20


def build_dashboard_tab(
    run_id: str,
    novel_id: str,
    session: Session,
    metrics_service: MetricsService,
    run: dict[str, Any],
) -> dict[str, Any]:
    """
    仪表盘 tab：四组聚合指标 + 章节汇总 + 主题词 + 诊断 + 情绪趋势一次拉取

    聚合指标复用 MetricsService 缓存（300s）；情绪趋势固定全书窗口 20 段
    （与原 NovelDetailPage 并发请求的参数一致）。
    """
    paragraph_repo = ParagraphRepository(session)
    annotation_repo = AnnotationRepository(session)
    stats_repo = StatsRepository(session)

    narrative_structure, emotion_stats, character_stats, style_stats = metrics_service.get_aggregate_result(
        run_id, session
    )
    return {
        "run_id": run_id,
        "narrative_structure": narrative_structure,
        "emotion_stats": emotion_stats,
        "character_stats": character_stats,
        "style_stats": style_stats,
        "chapter_metrics": _fetch_chapter_metrics(run_id, paragraph_repo, annotation_repo, run),
        "topics": _fetch_topics(run_id, paragraph_repo),
        "diagnosis": _fetch_diagnosis(run_id, novel_id, stats_repo),
        "emotion_trend": _fetch_emotion_trend(run_id, paragraph_repo, None, None, _DASHBOARD_WINDOW_PARAGRAPHS),
    }


def build_rhythm_tab(
    run_id: str, session: Session, metrics_service: MetricsService, max_points: int | None
) -> dict[str, Any]:
    """节奏张力 tab：段落曲线（max_points 仅展示降采样）+ 叙事结构高潮参数"""
    paragraph_repo = ParagraphRepository(session)
    return {
        "run_id": run_id,
        "curves": _fetch_paragraph_curves(run_id, paragraph_repo, max_points),
        "narrative_structure": metrics_service.get_narrative_structure(run_id, session),
    }
