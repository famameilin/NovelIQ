"""
聚合流程核心业务逻辑

供 workflows 模块使用。

曲线事实源为 paragraph_curves（预处理落库），聚合阶段不重算 chunk 曲线；
全局统计（global_stats）从段落充分统计量按守恒口径聚合计算。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from src.fact_graph.errors import GraphReadinessError
from src.metrics.queries.aggregate import query_aggregate_metrics
from src.sse.events import StreamEvent
from src.storage.repositories import ChapterRepository, StatsRepository
from src.storage.repositories.paragraph_repository import ParagraphRepository
from src.work.queries import is_annotate_complete

QUALITY_TARGETS = {
    "tone_distribution_non_empty_rate": 1.0,
    "imagery_density_non_null_rate": 1.0,
    "imagery_lexicon_null_chapter_ratio_max": 0.0,
}


def _log_aggregate_results(agg_result) -> None:
    """输出聚合指标日志"""
    logger.info("\n=== Aggregate Metrics ===")

    if agg_result.narrative_structure:
        logger.info("\n--- Narrative Structure ---")
        for key, value in agg_result.narrative_structure.items():
            if isinstance(value, float):
                logger.info(f"  {key}: {value:.4f}")
            else:
                logger.info(f"  {key}: {value}")

    if agg_result.emotion_curve:
        logger.info("\n--- Emotion Curve ---")
        for key, value in agg_result.emotion_curve.items():
            if isinstance(value, float):
                logger.info(f"  {key}: {value:.4f}")
            else:
                logger.info(f"  {key}: {value}")

    if agg_result.character_relations:
        logger.info("\n--- Character Relations ---")
        for key, value in agg_result.character_relations.items():
            if isinstance(value, float):
                logger.info(f"  {key}: {value:.4f}")
            elif isinstance(value, dict):
                logger.info(f"  {key}: {value}")
            else:
                logger.info(f"  {key}: {value}")

    if agg_result.language_style:
        logger.info("\n--- Language Style ---")
        if isinstance(agg_result.language_style, dict):
            for key, value in agg_result.language_style.items():
                if isinstance(value, float):
                    logger.info(f"  {key}: {value:.4f}")
                else:
                    logger.info(f"  {key}: {value}")


def _build_quality_gate_report(run_id: str, agg_result, session: Session) -> dict[str, Any]:
    """构建聚合质量门报告

    imagery 完整性按章节从段落指标充分统计量聚合判定：
    章 imagery 密度 = Σimagery_hit_count / Σtoken_count；token 为 0 的章
    视为缺失（不通过），零命中的章不算质量错误；数据存在性按全书
    Σimagery_hit_count > 0 判定。
    """
    language_style = agg_result.language_style if isinstance(agg_result.language_style, dict) else {}

    tone_distribution = language_style.get("tone_distribution")
    tone_non_empty = isinstance(tone_distribution, dict) and len(tone_distribution) > 0

    aggregates = ParagraphRepository(session).fetch_chapter_metric_aggregates(run_id)
    totals_by_chapter = dict(aggregates)
    imagery_total = sum(float(totals.get("imagery_hit_count", 0.0)) for _chapter_id, totals in aggregates)
    imagery_non_null = imagery_total > 0
    # 分母为"有正文的全部章节"：aggregates 从 ParagraphMetric 内连接出发，
    # 无指标行的章不出现在其中，按 token 0（缺失）计入不通过
    chapter_ids_with_text = [chapter_id for chapter_id, _ in ChapterRepository(session).fetch_chapter_texts(run_id)]
    null_chapter_ids: list[int] = []
    for chapter_id in chapter_ids_with_text:
        totals = totals_by_chapter.get(chapter_id)
        token_count = float(totals.get("token_count", 0.0)) if totals is not None else 0.0
        if token_count <= 0:
            null_chapter_ids.append(chapter_id)

    if chapter_ids_with_text:
        null_ratio = len(null_chapter_ids) / len(chapter_ids_with_text)
    else:
        # 无正文章节数据时按"不通过"处理：0/0 不等于达标，避免"无数据=通过质量门"
        null_ratio = 1.0

    return {
        "tone_distribution_non_empty_rate": 1.0 if tone_non_empty else 0.0,
        "imagery_density_non_null_rate": 1.0 if imagery_non_null else 0.0,
        "imagery_lexicon_null_chapter_ratio": null_ratio,
        "imagery_lexicon_null_chapter_ids": null_chapter_ids,
    }


def _log_quality_gate_report(run_id: str, report: dict[str, Any]) -> None:
    tone_rate = float(report.get("tone_distribution_non_empty_rate", 0.0))
    imagery_rate = float(report.get("imagery_density_non_null_rate", 0.0))
    null_ratio = float(report.get("imagery_lexicon_null_chapter_ratio", 0.0))
    null_chapter_ids = report.get("imagery_lexicon_null_chapter_ids", [])

    logger.info("\n=== Aggregate Quality Gate ===")
    logger.info(f"tone_distribution_non_empty_rate={tone_rate:.0%}")
    logger.info(f"imagery_density_non_null_rate={imagery_rate:.0%}")
    logger.info(f"imagery_lexicon_null_chapter_ratio={null_ratio:.2%}")

    if tone_rate < QUALITY_TARGETS["tone_distribution_non_empty_rate"]:
        logger.warning(f"[quality-gate] tone_distribution empty (run_id={run_id})")

    if imagery_rate < QUALITY_TARGETS["imagery_density_non_null_rate"]:
        logger.warning(f"[quality-gate] imagery_density is null (run_id={run_id})")

    if null_ratio > QUALITY_TARGETS["imagery_lexicon_null_chapter_ratio_max"]:
        logger.warning(
            f"[quality-gate] imagery lexicon null chunk ratio {null_ratio * 100:.2f}% exceeds target "
            f"{QUALITY_TARGETS['imagery_lexicon_null_chapter_ratio_max'] * 100:.2f}% (run_id={run_id})"
        )
        logger.warning(f"[quality-gate] imagery lexicon null chapter_ids={null_chapter_ids}")


async def run_aggregate(
    run_id: str,
    session: Session,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> tuple[int, int, int]:
    """执行聚合流程：写 global_stats(守恒聚合)并跑 /metrics。

    Args: run_id / session / emitter(async StreamEvent->None)  Returns: (总章数, 全局统计条数, 保留位0)
    """
    from src.utils.cancellation import check_cancelled

    start_time = time.time()
    # 编排器 session 是长活事务，边界检查必须用短事务版
    # （详见 require_released_cutoff_short docstring）
    from src.storage.repositories.annotation import AnnotationRepository

    if not is_annotate_complete(AnnotationRepository(session).session, run_id):
        raise ValueError("必需角色 work 尚未全部成功保存，不能聚合")

    chapter_repo = ChapterRepository(session)
    stats_repo = StatsRepository(session)
    ann_repo = AnnotationRepository(session)

    chunk_texts = chapter_repo.fetch_chapter_texts(run_id)

    if not chunk_texts:
        logger.warning("no chunks found in db")
        return 0, 0, 0

    total_chapters = len(chunk_texts)
    logger.info(f"loaded {total_chapters} chunks from db")

    from src.metrics.queries.global_stats import save_global_stats

    check_cancelled(is_cancelled)
    global_stats = save_global_stats(session, run_id)
    logger.info(f"inserted {len(global_stats)} global stats")

    logger.info("Computing aggregate metrics...")
    try:
        # 指标聚合移出事件循环：全书章节/图事实的 CPU 聚合同为重活
        agg_result = await asyncio.to_thread(query_aggregate_metrics, run_id, ann_repo, chapter_repo, stats_repo)
        # 聚合是单次线程内调用，无法中途中断：返回后立刻兑现取消
        check_cancelled(is_cancelled)
        _log_aggregate_results(agg_result)
        quality_report = _build_quality_gate_report(run_id, agg_result, session)
        _log_quality_gate_report(run_id, quality_report)
    except GraphReadinessError as exc:
        # 图未就绪是可预期降级：保留降级但记录 error 级别日志
        logger.error(f"aggregate metrics skipped: graph not ready: {exc}")
    except Exception as e:
        logger.warning(f"Failed to compute aggregate metrics: {e}")

    elapsed = time.time() - start_time
    logger.info(f"aggregate completed chunks={total_chapters} global_stats={len(global_stats)} time={elapsed:.2f}s")
    logger.info("\n=== Aggregate Statistics ===")
    logger.info(f"Total chunks: {total_chapters}")
    logger.info(f"Global stats: {len(global_stats)}")
    logger.info(f"Processing time: {elapsed:.2f}s")

    if emitter:
        await emitter(
            StreamEvent(action="complete", stage="aggregate", current=1, total=1, percent=100.0, sub_percent=100.0)
        )

    return total_chapters, len(global_stats), 0
