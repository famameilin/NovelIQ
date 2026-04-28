"""
说明: Phase2 伏笔结果投影器，负责校验与 ChunkAnnotation 伏笔视图合并
"""

from __future__ import annotations

from loguru import logger

from src.models.local.parser import validate_foreshadowing_result
from src.models.local.schema import ChunkAnnotation, ForeshadowingResult


def normalize_foreshadowing_result(
    foreshadowing: ForeshadowingResult | None,
    text: str,
    chunk_id: int | None,
) -> ForeshadowingResult | None:
    """
    校验并归一化 Phase2 伏笔结果
    """
    if not foreshadowing:
        return None

    if not validate_foreshadowing_result(foreshadowing, text):
        return None

    logger.debug(
        "Foreshadowing found chunk_id={} type={}",
        chunk_id,
        foreshadowing.foreshadowing_type,
    )
    return foreshadowing


def merge_annotation_foreshadowing(
    annotation: ChunkAnnotation,
    foreshadowing: ForeshadowingResult | None,
    *,
    resolved_setup_id: str | None = None,
    resolved_setup_summary: str | None = None,
    resolved_payoff_likelihood: str | None = None,
) -> ChunkAnnotation:
    """
    将 Phase2 伏笔结果投影回 ChunkAnnotation 写入视图
    """
    if foreshadowing is None:
        return annotation

    has_foreshadowing = bool(foreshadowing.has_foreshadowing)
    return ChunkAnnotation(
        emotional_valence=annotation.emotional_valence,
        event_type=annotation.event_type,
        pivot_moment=annotation.pivot_moment,
        cliffhanger=annotation.cliffhanger,
        chunk_summary=annotation.chunk_summary,
        has_foreshadowing=has_foreshadowing,
        is_strong_setup=foreshadowing.is_strong_setup if has_foreshadowing else False,
        foreshadowing_type=foreshadowing.foreshadowing_type if has_foreshadowing else None,
        setup_kind=foreshadowing.setup_kind if has_foreshadowing else None,
        foreshadowing_desc=(
            f"{foreshadowing.anchor_text} - {foreshadowing.anchor_reason}" if has_foreshadowing else ""
        ),
        setup_summary=(resolved_setup_summary or foreshadowing.setup_summary) if has_foreshadowing else "",
        why_unresolved_now=foreshadowing.why_unresolved_now if has_foreshadowing else "",
        expected_payoff_family=foreshadowing.expected_payoff_family if has_foreshadowing else "",
        payoff_likelihood=(
            resolved_payoff_likelihood or foreshadowing.payoff_likelihood
            if has_foreshadowing
            else None
        ),
        linked_setup_id=resolved_setup_id if has_foreshadowing else None,
        characters=annotation.characters,
        dialogues=annotation.dialogues,
        location_appearances=annotation.location_appearances,
        dialogue_lengths=annotation.dialogue_lengths,
    )
