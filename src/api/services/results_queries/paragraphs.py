"""
段落级结果查询组装器

说明: 承载 paragraph-curves（§13.1）与 chapter-metrics（§13.2）的查询组装逻辑。

聚合口径（设计文档《章节粒度分析指标重设计》§8）：
- 比率一律分子/分母聚合，禁止平均段落密度（§8.1）
- 句长均值/方差从充分统计量（count/sum/sum_sq）恢复（§8.2）
- TTR/MTLD 等非可加指标在目标文本序列上直接计算（§8.3）
- 曲线展示降采样只发生在 API 传输层，不参与指标计算（§9.4）
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from src.api.models.responses import (
    BookAggregateStats,
    ChapterMetricsResponse,
    ChapterMetricSummary,
    EmotionTrendWindow,
    ParagraphCurvePoint,
)
from src.config import settings
from src.metrics.robust_smooth import robust_local_regression
from src.metrics.style_metrics import mtld, ttr
from src.preprocess.tokenize import tokenize
from src.storage.repositories import AnnotationRepository, ParagraphRepository
from src.utils.lttb import sample_paragraph_curve_points


def _paragraph_splitter_version() -> str:
    """paragraphs 行写入时使用的切分器版本（与 ParagraphRepository 读取逻辑一致）"""
    return str(getattr(getattr(settings, "paragraphs", None), "splitter_version", None) or "1")


def _metric_version() -> str:
    return str(getattr(settings.metrics, "metric_version", None) or "2")


def _curve_version() -> str:
    return str(getattr(settings.metrics, "curve_version", None) or "1")


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    """分母 <= 0 时返回 None（§15.2：分母为零不伪造数值）"""
    if denominator <= 0:
        return None
    return numerator / denominator


def _clamp_coverage(value: float | None) -> float | None:
    """2026-08-15 将后端平滑覆盖率限制在可解释的 0~1 值域"""
    if value is None:
        return None
    return max(0.0, min(1.0, value))


def _smooth_emotion_windows(windows: list[EmotionTrendWindow]) -> list[EmotionTrendWindow]:
    """2026-08-15 对窗口聚合结果执行后端 LOWESS 展示平滑并保留原始值"""
    if not windows:
        return windows

    positions = [window.position for window in windows]
    weights = [float(max(window.token_total, 1)) for window in windows]
    min_points = int(getattr(settings.metrics, "lowess_min_points", 7) or 7)
    bandwidth = float(getattr(settings.metrics, "lowess_bandwidth", 0.02) or 0.02)

    def smooth_values(values: list[float | None]) -> list[float | None]:
        valid = [(index, value) for index, value in enumerate(values) if value is not None]
        if not valid:
            return [None] * len(values)
        fitted = robust_local_regression(
            [positions[index] for index, _ in valid],
            [float(value) for _, value in valid],
            weights=[weights[index] for index, _ in valid],
            bandwidth=bandwidth,
            min_points=min_points,
        )
        mapped: list[float | None] = [None] * len(values)
        for (index, _), value in zip(valid, fitted, strict=True):
            mapped[index] = float(value)
        return mapped

    pos_coverage = smooth_values([window.pos_coverage for window in windows])
    neg_coverage = smooth_values([window.neg_coverage for window in windows])
    pooled_pos = smooth_values([window.pooled_pos_density for window in windows])
    pooled_neg = smooth_values([window.pooled_neg_density for window in windows])
    pooled_net = smooth_values([window.pooled_net_density for window in windows])

    return [
        window.model_copy(
            update={
                "smoothed_pos_coverage": (
                    _clamp_coverage(pos_coverage[index])
                ),
                "smoothed_neg_coverage": (
                    _clamp_coverage(neg_coverage[index])
                ),
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
    """
    2026-08-15 由段落原始指标构造情绪趋势窗口并附带后端展示平滑值

    情绪趋势窗口聚合（§13.1 展示层，缩放自适应窗口）

    - 输入为段落充分统计量（paragraphs + paragraph_metrics 对齐），
      命中判定用原始分子（positive_weight_sum/negative_weight_sum > 0），
      请求时无词典/分词开销
    - 每窗段落数 window_paragraphs 作用于 range 过滤后的段落集，服务端钳制到 5~40
    - 覆盖率为命中段占比；池化密度为分子/分母聚合（§8.1），分母为零返回 None
    - 返回同时保留原始聚合值与后端 LOWESS 展示值，避免平滑覆盖可审计数据
    """
    paragraph_rows = paragraph_repo.fetch_paragraph_rows(run_id)
    metric_rows = paragraph_repo.fetch_paragraph_metrics(run_id)
    metric_by_paragraph_id = {int(row.paragraph_id): row for row in metric_rows}

    total_chars = sum(int(row.char_count) for row in paragraph_rows)

    entries: list[tuple[Any, Any, float]] = []
    for row in paragraph_rows:
        metric = metric_by_paragraph_id.get(int(row.paragraph_id))
        if metric is None:
            continue
        midpoint = (int(row.global_start_char) + int(row.global_end_char)) / 2
        position = midpoint / total_chars if total_chars > 0 else 0.0
        if range_start is not None:
            if range_end is None or position < range_start or position > range_end:
                continue
        entries.append((row, metric, position))

    paragraph_total = len(entries)
    if paragraph_total == 0:
        return []

    window_size = max(5, min(40, int(window_paragraphs)))

    windows: list[EmotionTrendWindow] = []
    for index in range(0, paragraph_total, window_size):
        chunk = entries[index : index + window_size]
        token_total = sum(int(metric.token_count) for _, metric, _ in chunk)
        pos_sum = sum(float(metric.positive_weight_sum) for _, metric, _ in chunk)
        neg_sum = sum(float(metric.negative_weight_sum) for _, metric, _ in chunk)
        pos_hit = sum(
            1 for _, metric, _ in chunk if float(metric.positive_weight_sum) > 0
        )
        neg_hit = sum(
            1 for _, metric, _ in chunk if float(metric.negative_weight_sum) > 0
        )
        hit_paragraphs = sum(
            1
            for _, metric, _ in chunk
            if float(metric.positive_weight_sum) + float(metric.negative_weight_sum) > 0
        )
        count = len(chunk)
        first_row, _, first_position = chunk[0]
        _, _, last_position = chunk[-1]
        center_position = (first_position + last_position) / 2.0
        windows.append(
            EmotionTrendWindow(
                window_index=index // window_size,
                position=center_position,
                start_position=first_position,
                end_position=last_position,
                paragraph_start=int(first_row.paragraph_id),
                paragraph_end=int(chunk[-1][0].paragraph_id),
                chapter_start=int(first_row.chapter_id),
                chapter_end=int(chunk[-1][0].chapter_id),
                pos_coverage=pos_hit / count,
                neg_coverage=neg_hit / count,
                pooled_pos_density=_safe_ratio(pos_sum, token_total),
                pooled_neg_density=_safe_ratio(neg_sum, token_total),
                pooled_net_density=_safe_ratio(pos_sum - neg_sum, token_total),
                token_total=token_total,
                hit_paragraphs=hit_paragraphs,
                paragraph_total=count,
            )
        )

    return _smooth_emotion_windows(windows)


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

    must_keep_indices = _must_keep_curve_indices(points)
    sampled_indices = sample_paragraph_curve_points(
        [point.model_dump() for point in points],
        max_points,
        must_keep_indices=must_keep_indices,
        value_key="net_density",
    )
    return [points[index] for index in sampled_indices]


def _must_keep_curve_indices(points: list[ParagraphCurvePoint]) -> list[int]:
    """章节边界（每章首个与末个段落）+ net_density 全局峰值索引（None 按 0）"""
    keep_set: set[int] = set()
    chapter_first_last: dict[int, list[int]] = {}
    for index, point in enumerate(points):
        bounds = chapter_first_last.setdefault(point.chapter_id, [index, index])
        bounds[1] = index
    for first_index, last_index in chapter_first_last.values():
        keep_set.add(first_index)
        keep_set.add(last_index)

    best_index = -1
    best_value: float | None = None
    for index, point in enumerate(points):
        value = float(point.net_density) if point.net_density is not None else 0.0
        if best_value is None or value > best_value:
            best_value = value
            best_index = index
    if best_index >= 0:
        keep_set.add(best_index)

    return sorted(keep_set)


@dataclass
class _ChapterAccumulator:
    """章节分子/分母与充分统计量累加器（§8.1/8.2）"""

    chapter_id: int
    paragraph_count: int = 0
    total_chars: int = 0
    total_tokens: int = 0
    positive_weight_sum: float = 0.0
    negative_weight_sum: float = 0.0
    fight_weight_sum: float = 0.0
    exclaim_count: int = 0
    question_count: int = 0
    pause_count: int = 0
    dialogue_char_count: int = 0
    sentence_count: int = 0
    sentence_char_sum: float = 0.0
    sentence_char_sum_sq: float = 0.0
    texts: list[str] = field(default_factory=list)


def _fetch_chapter_metrics(
    run_id: str,
    paragraph_repo: ParagraphRepository,
    annotation_repo: AnnotationRepository,
    run: dict[str, Any],
) -> ChapterMetricsResponse:
    """
    获取章节与全书汇总指标（§13.2）

    - 章节来自段落聚合（fetch_paragraph_rows + fetch_paragraph_metrics 按
      paragraph_id 对齐，缺任一侧的段落跳过），章节顺序与全文段落顺序一致
    - 章节/全书 TTR、MTLD 在拼接后的章节/全书文本上直接计算一次
    - 章节标签来自 fetch_chapter_annotations_full（按 chapter_id 映射），
      无标注的章节对应字段为 None
    """
    paragraph_rows = paragraph_repo.fetch_paragraph_rows(run_id)
    metric_rows = paragraph_repo.fetch_paragraph_metrics(run_id)
    metric_by_paragraph_id = {int(row.paragraph_id): row for row in metric_rows}
    annotation_rows = annotation_repo.fetch_chapter_annotations_full(run_id)
    annotation_by_chapter_id = {int(row.chapter_id): row for row in annotation_rows}

    chapters_by_id: dict[int, _ChapterAccumulator] = {}
    first_paragraph_by_chapter: dict[int, Any] = {}
    for paragraph_row in paragraph_rows:
        metric_row = metric_by_paragraph_id.get(int(paragraph_row.paragraph_id))
        if metric_row is None:
            continue
        chapter_id = int(paragraph_row.chapter_id)
        first_paragraph_by_chapter.setdefault(chapter_id, paragraph_row)
        accumulator = chapters_by_id.setdefault(
            chapter_id, _ChapterAccumulator(chapter_id=chapter_id)
        )
        accumulator.paragraph_count += 1
        accumulator.total_chars += int(paragraph_row.char_count)
        accumulator.total_tokens += int(metric_row.token_count)
        accumulator.positive_weight_sum += float(metric_row.positive_weight_sum)
        accumulator.negative_weight_sum += float(metric_row.negative_weight_sum)
        accumulator.fight_weight_sum += float(metric_row.fight_weight_sum)
        accumulator.exclaim_count += int(metric_row.exclaim_count)
        accumulator.question_count += int(metric_row.question_count)
        accumulator.pause_count += int(metric_row.pause_count)
        accumulator.dialogue_char_count += int(metric_row.dialogue_char_count)
        accumulator.sentence_count += int(metric_row.sentence_count)
        accumulator.sentence_char_sum += float(metric_row.sentence_char_sum)
        accumulator.sentence_char_sum_sq += float(metric_row.sentence_char_sum_sq)
        accumulator.texts.append(str(paragraph_row.text))

    chapter_metrics: list[ChapterMetricSummary] = []
    for accumulator in chapters_by_id.values():
        first_paragraph = first_paragraph_by_chapter[accumulator.chapter_id]
        annotation = annotation_by_chapter_id.get(int(first_paragraph.chapter_id))
        chapter_metrics.append(_build_chapter_summary(accumulator, annotation))

    book = _build_book_aggregate(chapter_metrics, chapters_by_id, run)
    return ChapterMetricsResponse(chapters=chapter_metrics, book=book)


def _build_chapter_summary(
    accumulator: _ChapterAccumulator,
    annotation: Any | None,
) -> ChapterMetricSummary:
    tokens = tokenize("".join(accumulator.texts)) if accumulator.texts else []
    sentence_mean = _safe_ratio(accumulator.sentence_char_sum, accumulator.sentence_count)
    sentence_var: float | None = None
    if accumulator.sentence_count > 0 and sentence_mean is not None:
        sentence_var = max(
            0.0,
            accumulator.sentence_char_sum_sq / accumulator.sentence_count
            - sentence_mean * sentence_mean,
        )
    return ChapterMetricSummary(
        chapter_id=accumulator.chapter_id,
        paragraph_count=accumulator.paragraph_count,
        total_chars=accumulator.total_chars,
        total_tokens=accumulator.total_tokens,
        pos_density=_safe_ratio(accumulator.positive_weight_sum, accumulator.total_tokens),
        neg_density=_safe_ratio(accumulator.negative_weight_sum, accumulator.total_tokens),
        net_density=_safe_ratio(
            accumulator.positive_weight_sum - accumulator.negative_weight_sum,
            accumulator.total_tokens,
        ),
        fight_density=_safe_ratio(accumulator.fight_weight_sum, accumulator.total_tokens),
        exclaim_per_100_chars=_safe_ratio(accumulator.exclaim_count * 100.0, accumulator.total_chars),
        question_per_100_chars=_safe_ratio(accumulator.question_count * 100.0, accumulator.total_chars),
        pause_per_100_chars=_safe_ratio(accumulator.pause_count * 100.0, accumulator.total_chars),
        dialogue_ratio=_safe_ratio(accumulator.dialogue_char_count, accumulator.total_chars),
        avg_sent_len=sentence_mean,
        sent_len_std=math.sqrt(sentence_var) if sentence_var is not None else None,
        ttr=ttr(tokens) if tokens else None,
        mtld=mtld(tokens) if tokens else None,
        narrative_function=(
            str(annotation.event_type) if annotation is not None and annotation.event_type else None
        ),
        pivot_moment=(
            bool(annotation.pivot_moment)
            if annotation is not None and annotation.pivot_moment is not None
            else None
        ),
        cliffhanger=(
            bool(annotation.cliffhanger)
            if annotation is not None and annotation.cliffhanger is not None
            else None
        ),
        emotional_valence=(
            str(annotation.emotional_valence)
            if annotation is not None and annotation.emotional_valence
            else None
        ),
    )


def _build_book_aggregate(
    chapter_metrics: list[ChapterMetricSummary],
    chapters_by_id: dict[int, _ChapterAccumulator],
    run: dict[str, Any],
) -> BookAggregateStats:
    total_chapters = len(chapter_metrics)
    total_paragraphs = sum(item.paragraph_count for item in chapter_metrics)
    total_chars = sum(item.total_chars for item in chapter_metrics)
    total_tokens = sum(item.total_tokens for item in chapter_metrics)
    positive_weight_sum = sum(acc.positive_weight_sum for acc in chapters_by_id.values())
    negative_weight_sum = sum(acc.negative_weight_sum for acc in chapters_by_id.values())
    fight_weight_sum = sum(acc.fight_weight_sum for acc in chapters_by_id.values())
    exclaim_count = sum(acc.exclaim_count for acc in chapters_by_id.values())
    question_count = sum(acc.question_count for acc in chapters_by_id.values())
    pause_count = sum(acc.pause_count for acc in chapters_by_id.values())
    dialogue_char_count = sum(acc.dialogue_char_count for acc in chapters_by_id.values())
    sentence_count = sum(acc.sentence_count for acc in chapters_by_id.values())
    sentence_char_sum = sum(acc.sentence_char_sum for acc in chapters_by_id.values())
    sentence_char_sum_sq = sum(acc.sentence_char_sum_sq for acc in chapters_by_id.values())

    book_text = "".join(text for acc in chapters_by_id.values() for text in acc.texts)
    book_tokens = tokenize(book_text) if book_text else []

    sentence_mean = _safe_ratio(sentence_char_sum, sentence_count)
    sentence_var: float | None = None
    if sentence_count > 0 and sentence_mean is not None:
        sentence_var = max(
            0.0, sentence_char_sum_sq / sentence_count - sentence_mean * sentence_mean
        )

    narrative_share: dict[str, float] = {}
    valence_share: dict[str, float] = {}
    pivot_chapters = 0
    pivot_valid_chapters = 0
    cliffhanger_chapters = 0
    cliffhanger_valid_chapters = 0
    narrative_valid_chapters = 0
    valence_valid_chapters = 0
    for chapter in chapter_metrics:
        if chapter.narrative_function:
            narrative_valid_chapters += 1
            narrative_share[chapter.narrative_function] = (
                narrative_share.get(chapter.narrative_function, 0.0) + 1.0
            )
        if chapter.emotional_valence:
            valence_valid_chapters += 1
            valence_share[chapter.emotional_valence] = (
                valence_share.get(chapter.emotional_valence, 0.0) + 1.0
            )
        if chapter.pivot_moment is not None:
            pivot_valid_chapters += 1
            if chapter.pivot_moment:
                pivot_chapters += 1
        if chapter.cliffhanger is not None:
            cliffhanger_valid_chapters += 1
            if chapter.cliffhanger:
                cliffhanger_chapters += 1

    if narrative_valid_chapters > 0:
        narrative_share = {
            label: round(count / narrative_valid_chapters, 6) for label, count in narrative_share.items()
        }
    if valence_valid_chapters > 0:
        valence_share = {
            label: round(count / valence_valid_chapters, 6) for label, count in valence_share.items()
        }

    return BookAggregateStats(
        total_chapters=total_chapters,
        total_paragraphs=total_paragraphs,
        total_chars=total_chars,
        total_tokens=total_tokens,
        pos_density=_safe_ratio(positive_weight_sum, total_tokens),
        neg_density=_safe_ratio(negative_weight_sum, total_tokens),
        net_density=_safe_ratio(positive_weight_sum - negative_weight_sum, total_tokens),
        fight_density=_safe_ratio(fight_weight_sum, total_tokens),
        exclaim_per_100_chars=_safe_ratio(exclaim_count * 100.0, total_chars),
        question_per_100_chars=_safe_ratio(question_count * 100.0, total_chars),
        pause_per_100_chars=_safe_ratio(pause_count * 100.0, total_chars),
        dialogue_ratio=_safe_ratio(dialogue_char_count, total_chars),
        avg_sent_len=sentence_mean,
        sent_len_std=math.sqrt(sentence_var) if sentence_var is not None else None,
        ttr=ttr(book_tokens) if book_tokens else None,
        mtld=mtld(book_tokens) if book_tokens else None,
        chapter_narrative_function_share=narrative_share,
        chapter_pivot_rate=(
            pivot_chapters / pivot_valid_chapters if pivot_valid_chapters > 0 else None
        ),
        chapter_cliffhanger_rate=(
            cliffhanger_chapters / cliffhanger_valid_chapters
            if cliffhanger_valid_chapters > 0
            else None
        ),
        chapter_emotional_valence_share=valence_share,
        analysis_contract_version=str(run.get("analysis_contract_version") or "paragraph-v1"),
        paragraph_splitter_version=_paragraph_splitter_version(),
        metric_version=_metric_version(),
        curve_version=_curve_version(),
    )
