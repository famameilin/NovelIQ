"""
聚合流程核心业务逻辑

创建时间: 2026-03-14
创建者: TraeAI
任务: refactor-cli-layer-functions
说明: 从 src/cli/aggregate.py 提取的核心业务逻辑，用于 workflows 模块

修改时间: 2026-03-14
修改者: TraeAI
任务: workflows 使用 Repository 模式重构
修改内容: 添加 run_id/session 参数支持，使用 ChunkRepository/StatsRepository 替代直接调用 operations 函数

修改时间: 2026-03-15
修改者: TraeAI
任务: storage-layer-decoupling
修改内容: 移除向后兼容代码，只保留 Repository 模式
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import List, Tuple

from loguru import logger
from sqlalchemy.orm import Session

from src.workflows.curve_metrics import (
    compute_emotion_curve,
    compute_global_stats,
    compute_rhythm_curve,
    compute_tension_signals,
    load_all_lexicons,
)
from src.metrics.aggregate_metrics import aggregate_all_metrics
from src.storage.repositories import ChunkRepository, StatsRepository, AnnotationRepository


def _compute_tension_composite(signals: List[dict]) -> List[float]:
    if not signals:
        return []
    keys = ["emotion_intensity", "dialogue_ratio", "sent_len_std", "event_score", "cliffhanger_score"]
    mins = {key: min(item.get(key, 0.0) for item in signals) for key in keys}
    maxs = {key: max(item.get(key, 0.0) for item in signals) for key in keys}
    composites: List[float] = []
    for item in signals:
        total = 0.0
        for key in keys:
            value = item.get(key, 0.0)
            denom = maxs[key] - mins[key]
            if denom == 0:
                normalized = 0.0
            else:
                normalized = (value - mins[key]) / denom
            total += normalized
        composites.append(total / len(keys))
    return composites


def _log_aggregate_results(agg_result) -> None:
    """
    输出聚合结果日志

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-cli-layer-functions
    说明: 从 run_aggregate 中提取，负责输出聚合指标日志
    """
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

    if agg_result.traditional_culture:
        logger.info("\n--- Traditional Culture ---")
        for key, value in agg_result.traditional_culture.items():
            if isinstance(value, float):
                logger.info(f"  {key}: {value:.4f}")
            else:
                logger.info(f"  {key}: {value}")


def run_aggregate(
    run_id: str,
    session: Session,
    cache_path: Path | None = None,
) -> Tuple[int, int, int]:
    """
    执行聚合流程

    创建时间: 2025-03-11
    创建者: TraeAI
    任务: 聚合流程

    修改时间: 2026-03-13
    修改者: TraeAI
    任务: refactor-cli-layer-functions
    修改内容: 提取日志输出为 _log_aggregate_results 辅助函数
    修改时间: 2026-03-14
    修改者: TraeAI
    任务: workflows 使用 Repository 模式重构
    修改内容: 添加 run_id/session 参数，支持 Repository 模式

    Args:
        run_id: 运行ID
        session: 数据库连接
        cache_path: 缓存路径

    Returns:
        Tuple[int, int, int]: (总块数, 情绪曲线行数, 节奏曲线行数)
    """
    start_time = time.time()

    chunk_repo = ChunkRepository(session)
    stats_repo = StatsRepository(session)
    ann_repo = AnnotationRepository(session)

    chunk_texts = chunk_repo.fetch_chunk_texts(run_id)

    if not chunk_texts:
        logger.warning("no chunks found in db")
        return 0, 0, 0

    total_chunks = len(chunk_texts)
    logger.info(f"loaded {total_chunks} chunks from db")

    lexicon_dir = Path("data/lexicons")
    lexicons = load_all_lexicons(lexicon_dir)
    pos_terms = lexicons["positive"]
    neg_terms = lexicons["negative"]
    fight_terms = lexicons["combat"]

    emotion_rows, raw_densities = compute_emotion_curve(chunk_texts, pos_terms, neg_terms)

    stats_repo.insert_emotion_curve(run_id, emotion_rows)
    logger.info(f"inserted {len(emotion_rows)} emotion curve rows")

    chunk_annotations = ann_repo.fetch_chunk_annotations(run_id)
    chunk_styles = chunk_repo.fetch_chunk_styles(run_id)

    annotation_map = {row[0]: (row[1], row[2]) for row in chunk_annotations}
    style_map = {row[0]: (row[1], row[2], row[3]) for row in chunk_styles}

    tension_signals = compute_tension_signals(chunk_texts, fight_terms, style_map, annotation_map, raw_densities)
    tension_composite_values = _compute_tension_composite(tension_signals)
    rhythm_rows = compute_rhythm_curve(chunk_texts, fight_terms, tension_composite_values)

    stats_repo.insert_rhythm_curve(run_id, rhythm_rows)
    logger.info(f"inserted {len(rhythm_rows)} rhythm curve rows")

    global_stats = compute_global_stats(session, raw_densities, tension_composite_values, chunk_texts)

    stats_repo.insert_global_stats(run_id, global_stats)
    logger.info(f"inserted {len(global_stats)} global stats")

    logger.info("Computing aggregate metrics...")
    try:
        agg_result = aggregate_all_metrics(run_id, ann_repo, chunk_repo, stats_repo)
        _log_aggregate_results(agg_result)
    except Exception as e:
        logger.warning(f"Failed to compute aggregate metrics: {e}")

    elapsed = time.time() - start_time
    logger.info(
        f"aggregate completed chunks={total_chunks} emotion_rows={len(emotion_rows)} rhythm_rows={len(rhythm_rows)} time={elapsed:.2f}s"
    )
    logger.info("\n=== Aggregate Statistics ===")
    logger.info(f"Total chunks: {total_chunks}")
    logger.info(f"Emotion curve rows: {len(emotion_rows)}")
    logger.info(f"Rhythm curve rows: {len(rhythm_rows)}")
    logger.info(f"Global stats: {len(global_stats)}")
    logger.info(f"Processing time: {elapsed:.2f}s")
    return total_chunks, len(emotion_rows), len(rhythm_rows)
