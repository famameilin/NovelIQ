"""仪表盘与节奏张力 tab 组装"""

from __future__ import annotations

from typing import Any

from src.api.services.metrics_service import MetricsService
from src.api.services.results_queries.diagnosis import _fetch_diagnosis
from src.api.services.results_queries.paragraphs import (
    _fetch_chapter_metrics,
    _fetch_emotion_trend,
    _fetch_paragraph_curves,
)
from src.api.services.results_queries.topics import _fetch_topics
from src.metrics.queries.annotations import fetch_chapter_annotations_full
from src.storage import Storage
from src.text_processing.tokenize import reuse_token_blocks

_DASHBOARD_WINDOW_PARAGRAPHS = 20


def build_dashboard_tab(
    run_id: str,
    novel_id: str,
    session: Storage,
    metrics_service: MetricsService,
    run: dict[str, Any],
) -> dict[str, Any]:
    """
    仪表盘 tab：四组聚合指标 + 章节汇总 + 主题词 + 诊断 + 情绪趋势一次拉取

    情绪趋势固定全书窗口 20 段
    """
    paragraph_repo = session.paragraphs
    annotation_rows = fetch_chapter_annotations_full(session, run_id, include_details=False)

    with reuse_token_blocks():
        narrative_structure, emotion_stats, character_stats, style_stats = metrics_service.compute_aggregate_result(
            run_id, session, annotation_rows=annotation_rows
        )
        paragraph_rows = paragraph_repo.fetch_paragraph_rows(run_id)
        metric_rows = paragraph_repo.fetch_paragraph_metrics(run_id)
        chapter_metrics = _fetch_chapter_metrics(
            run_id, paragraph_repo, session, run, paragraph_rows=paragraph_rows, metric_rows=metric_rows,
            annotation_rows=annotation_rows,
        )
    return {
        "run_id": run_id,
        "narrative_structure": narrative_structure,
        "emotion_stats": emotion_stats,
        "character_stats": character_stats,
        "style_stats": style_stats,
        "chapter_metrics": chapter_metrics,
        "topics": _fetch_topics(run_id, paragraph_repo),
        "diagnosis": _fetch_diagnosis(run_id, novel_id, session),
        "emotion_trend": _fetch_emotion_trend(
            run_id, paragraph_repo, None, None, _DASHBOARD_WINDOW_PARAGRAPHS,
            paragraph_rows=paragraph_rows, metric_rows=metric_rows,
        ),
    }


def build_rhythm_tab(
    run_id: str, session: Storage, metrics_service: MetricsService, max_points: int | None
) -> dict[str, Any]:
    """节奏张力 tab：段落曲线（max_points 仅展示降采样）+ 叙事结构高潮参数"""
    paragraph_repo = session.paragraphs
    return {
        "run_id": run_id,
        "curves": _fetch_paragraph_curves(run_id, paragraph_repo, max_points),
        "narrative_structure": metrics_service.get_narrative_structure(run_id, session),
    }
