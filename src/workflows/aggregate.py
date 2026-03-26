"""
鑱氬悎娴佺▼鏍稿績涓氬姟閫昏緫

鍒涘缓鏃堕棿: 2026-03-14
鍒涘缓鑰? TraeAI
浠诲姟: refactor-cli-layer-functions
璇存槑: 浠?src/cli/aggregate.py 鎻愬彇鐨勬牳蹇冧笟鍔￠€昏緫锛岀敤浜?workflows 妯″潡

淇敼鏃堕棿: 2026-03-14
淇敼鑰? TraeAI
浠诲姟: workflows 浣跨敤 Repository 妯″紡閲嶆瀯
淇敼鍐呭: 娣诲姞 run_id/session 鍙傛暟鏀寔锛屼娇鐢?ChunkRepository/StatsRepository 鏇夸唬鐩存帴璋冪敤 operations 鍑芥暟

淇敼鏃堕棿: 2026-03-15
淇敼鑰? TraeAI
浠诲姟: storage-layer-decoupling
淇敼鍐呭: 绉婚櫎鍚戝悗鍏煎浠ｇ爜锛屽彧淇濈暀 Repository 妯″紡
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from src.metrics.aggregate import aggregate_all_metrics
from src.storage.repositories import AnnotationRepository, ChunkRepository, StatsRepository
from src.workflows.curve_metrics import (
    compute_emotion_curve,
    compute_global_stats,
    compute_rhythm_curve,
    compute_tension_signals,
    load_all_lexicons,
)

QUALITY_TARGETS = {
    "tone_distribution_non_empty_rate": 1.0,
    "imagery_density_non_null_rate": 1.0,
    "imagery_lexicon_null_chunk_ratio_max": 0.0,
}


def _compute_tension_composite(signals: list[dict]) -> list[float]:
    if not signals:
        return []
    keys = ["emotion_intensity", "dialogue_ratio", "sent_len_std", "event_score", "cliffhanger_score"]
    mins = {key: min(item.get(key, 0.0) for item in signals) for key in keys}
    maxs = {key: max(item.get(key, 0.0) for item in signals) for key in keys}
    composites: list[float] = []
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
    杈撳嚭鑱氬悎缁撴灉鏃ュ織

    鍒涘缓鏃堕棿: 2026-03-13
    鍒涘缓鑰? TraeAI
    浠诲姟: refactor-cli-layer-functions
    璇存槑: 浠?run_aggregate 涓彁鍙栵紝璐熻矗杈撳嚭鑱氬悎鎸囨爣鏃ュ織
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


def _build_quality_gate_report(run_id: str, agg_result, chunk_repo: ChunkRepository) -> dict[str, Any]:
    language_style = agg_result.language_style if isinstance(agg_result.language_style, dict) else {}
    traditional_culture = agg_result.traditional_culture if isinstance(agg_result.traditional_culture, dict) else {}

    tone_distribution = language_style.get("tone_distribution")
    tone_non_empty = isinstance(tone_distribution, dict) and len(tone_distribution) > 0

    imagery_density = traditional_culture.get("imagery_density")
    imagery_non_null = imagery_density is not None

    culture_rows = chunk_repo.fetch_chunk_cultures_full(run_id)
    null_chunk_ids: list[int] = []
    for row in culture_rows:
        if not row:
            continue
        chunk_id = int(row[0])
        density_values = list(row[1:])
        if density_values and any(value is None for value in density_values):
            null_chunk_ids.append(chunk_id)

    null_ratio = (len(null_chunk_ids) / len(culture_rows)) if culture_rows else 0.0

    return {
        "tone_distribution_non_empty_rate": 1.0 if tone_non_empty else 0.0,
        "imagery_density_non_null_rate": 1.0 if imagery_non_null else 0.0,
        "imagery_lexicon_null_chunk_ratio": null_ratio,
        "imagery_lexicon_null_chunk_ids": null_chunk_ids,
    }


def _log_quality_gate_report(run_id: str, report: dict[str, Any]) -> None:
    tone_rate = float(report.get("tone_distribution_non_empty_rate", 0.0))
    imagery_rate = float(report.get("imagery_density_non_null_rate", 0.0))
    null_ratio = float(report.get("imagery_lexicon_null_chunk_ratio", 0.0))
    null_chunk_ids = report.get("imagery_lexicon_null_chunk_ids", [])

    logger.info("\n=== Aggregate Quality Gate ===")
    logger.info(f"tone_distribution_non_empty_rate={tone_rate:.0%}")
    logger.info(f"imagery_density_non_null_rate={imagery_rate:.0%}")
    logger.info(f"imagery_lexicon_null_chunk_ratio={null_ratio:.2%}")

    if tone_rate < QUALITY_TARGETS["tone_distribution_non_empty_rate"]:
        logger.warning(f"[quality-gate] tone_distribution empty (run_id={run_id})")

    if imagery_rate < QUALITY_TARGETS["imagery_density_non_null_rate"]:
        logger.warning(f"[quality-gate] imagery_density is null (run_id={run_id})")

    if null_ratio > QUALITY_TARGETS["imagery_lexicon_null_chunk_ratio_max"]:
        logger.warning(
            f"[quality-gate] imagery lexicon null chunk ratio {null_ratio * 100:.2f}% exceeds target "
            f"{QUALITY_TARGETS['imagery_lexicon_null_chunk_ratio_max'] * 100:.2f}% (run_id={run_id})"
        )
        logger.warning(f"[quality-gate] imagery lexicon null chunk_ids={null_chunk_ids}")


def run_aggregate(
    run_id: str,
    session: Session,
    cache_path: Path | None = None,
) -> tuple[int, int, int]:
    """
    鎵ц鑱氬悎娴佺▼

    鍒涘缓鏃堕棿: 2025-03-11
    鍒涘缓鑰? TraeAI
    浠诲姟: 鑱氬悎娴佺▼

    淇敼鏃堕棿: 2026-03-13
    淇敼鑰? TraeAI
    浠诲姟: refactor-cli-layer-functions
    淇敼鍐呭: 鎻愬彇鏃ュ織杈撳嚭涓?_log_aggregate_results 杈呭姪鍑芥暟
    淇敼鏃堕棿: 2026-03-14
    淇敼鑰? TraeAI
    浠诲姟: workflows 浣跨敤 Repository 妯″紡閲嶆瀯
    淇敼鍐呭: 娣诲姞 run_id/session 鍙傛暟锛屾敮鎸?Repository 妯″紡

    Args:
        run_id: 杩愯ID
        session: 鏁版嵁搴撹繛鎺?        cache_path: 缂撳瓨璺緞

    Returns:
        Tuple[int, int, int]: (鎬诲潡鏁? 鎯呯华鏇茬嚎琛屾暟, 鑺傚鏇茬嚎琛屾暟)
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
        quality_report = _build_quality_gate_report(run_id, agg_result, chunk_repo)
        _log_quality_gate_report(run_id, quality_report)
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

