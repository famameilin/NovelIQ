"""
段落级结果查询组装器

说明: 承载 paragraph-curves（§13.1）、emotion-trend、chapter-metrics（§13.2）的
取数与响应装配；聚合口径与计算在 `src.metrics.aggregate.aggregations`。

曲线展示降采样只发生在 API 传输层，不参与指标计算（§9.4）。
"""

from __future__ import annotations

from typing import Any

from src.api.models.responses import (
    BookAggregateStats,
    ChapterMetricsResponse,
    ChapterMetricSummary,
    EmotionTrendWindow,
    ParagraphCurvePoint,
)
from src.metrics.aggregate.aggregations import (
    aggregate_chapter_metrics,
    aggregate_emotion_trend_windows,
)
from src.metrics.aggregate.algorithms import (
    clamp_coverage,
    must_keep_curve_indices,
    smooth_emotion_series,
)
from src.storage.repositories import AnnotationRepository, ParagraphRepository
from src.utils.lttb import sample_paragraph_curve_points


def _apply_emotion_smoothing(windows: list[EmotionTrendWindow]) -> list[EmotionTrendWindow]:
    """2026-08-15 在窗口聚合结果上追加后端 LOWESS 展示值（原始值保留，算法在 aggregate.algorithms）"""
    if not windows:
        return windows

    positions = [window.position for window in windows]
    weights = [float(max(window.token_total, 1)) for window in windows]

    def smooth(values: list[float | None]) -> list[float | None]:
        return smooth_emotion_series(values, positions=positions, weights=weights)

    pos_coverage = smooth([window.pos_coverage for window in windows])
    neg_coverage = smooth([window.neg_coverage for window in windows])
    pooled_pos = smooth([window.pooled_pos_density for window in windows])
    pooled_neg = smooth([window.pooled_neg_density for window in windows])
    pooled_net = smooth([window.pooled_net_density for window in windows])

    return [
        window.model_copy(
            update={
                "smoothed_pos_coverage": clamp_coverage(pos_coverage[index]),
                "smoothed_neg_coverage": clamp_coverage(neg_coverage[index]),
                "smoothed_pooled_pos_density": pooled_pos[index],
                "smoothed_pooled_neg_density": pooled_neg[index],
                "smoothed_pooled_net_density": pooled_net[index],
            }
        )
        for index, window in enumerate(windows)
    ]


def _fetch_emotion_trend(
    run_id: str,
    paragraph_repo: ParagraphRepository,
    range_start: float | None,
    range_end: float | None,
    window_paragraphs: int,
) -> list[EmotionTrendWindow]:
    """2026-08-15 由段落原始指标构造情绪趋势窗口并附带后端展示平滑值"""
    windows = aggregate_emotion_trend_windows(
        paragraph_repo.fetch_paragraph_rows(run_id),
        paragraph_repo.fetch_paragraph_metrics(run_id),
        range_start=range_start,
        range_end=range_end,
        window_paragraphs=window_paragraphs,
    )
    return _apply_emotion_smoothing([EmotionTrendWindow(**payload) for payload in windows])


def _fetch_paragraph_curves(
    run_id: str,
    paragraph_repo: ParagraphRepository,
    max_points: int | None,
) -> list[ParagraphCurvePoint]:
    """
    获取段落曲线（§13.1）

    - fetch_paragraph_rows + fetch_paragraph_curves 按 paragraph_id 对齐，
      缺任一侧的段落跳过
    - position = 段落字符中点 / 全书总字符数（total_chars <= 0 时为 0.0）
    - max_points 为 None 或 >= 点数时返回全量；否则 LTTB 保形降采样，
      章节边界段落与 net_density 全局峰值强制保留
    """
    paragraph_rows = paragraph_repo.fetch_paragraph_rows(run_id)
    curve_rows = paragraph_repo.fetch_paragraph_curves(run_id)
    curve_by_paragraph_id = {int(row.paragraph_id): row for row in curve_rows}

    total_chars = sum(int(row.char_count) for row in paragraph_rows)

    points: list[ParagraphCurvePoint] = []
    for row in paragraph_rows:
        curve = curve_by_paragraph_id.get(int(row.paragraph_id))
        if curve is None:
            continue
        midpoint = (int(row.global_start_char) + int(row.global_end_char)) / 2
        points.append(
            ParagraphCurvePoint(
                paragraph_id=int(row.paragraph_id),
                chapter_id=int(row.chapter_id),
                paragraph_index=int(row.paragraph_index),
                global_start_char=int(row.global_start_char),
                global_end_char=int(row.global_end_char),
                position=midpoint / total_chars if total_chars > 0 else 0.0,
                char_count=int(row.char_count),
                token_count=int(row.token_count),
                pos_density=curve.pos_density,
                neg_density=curve.neg_density,
                net_density=curve.net_density,
                smoothed_net_density=curve.smoothed_net_density,
                surface_tension=curve.surface_tension,
                smoothed_surface_tension=curve.smoothed_surface_tension,
            )
        )

    if max_points is None or max_points >= len(points):
        return points

    must_keep_indices = must_keep_curve_indices(
        [point.chapter_id for point in points],
        [point.net_density for point in points],
    )
    sampled_indices = sample_paragraph_curve_points(
        [point.model_dump() for point in points],
        max_points,
        must_keep_indices=must_keep_indices,
        value_key="net_density",
    )
    return [points[index] for index in sampled_indices]


def _fetch_chapter_metrics(
    run_id: str,
    paragraph_repo: ParagraphRepository,
    annotation_repo: AnnotationRepository,
    run: dict[str, Any],
) -> ChapterMetricsResponse:
    """
    获取章节与全书汇总指标（§13.2）

    - 章节来自段落聚合（paragraphs + paragraph_metrics 按 paragraph_id 对齐）
    - 章节标签来自 fetch_chapter_annotations_full（按 chapter_id 映射）
    """
    del run
    annotations_by_chapter_id = {
        int(row.chapter_id): row for row in annotation_repo.fetch_chapter_annotations_full(run_id)
    }
    payload = aggregate_chapter_metrics(
        paragraph_repo.fetch_paragraph_rows(run_id),
        paragraph_repo.fetch_paragraph_metrics(run_id),
        annotations_by_chapter_id,
    )
    return ChapterMetricsResponse(
        chapters=[ChapterMetricSummary(**chapter) for chapter in payload["chapters"]],
        book=BookAggregateStats(**payload["book"]),
    )
