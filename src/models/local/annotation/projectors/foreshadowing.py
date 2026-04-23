"""
创建时间: 2026-04-23
任务: annotation-projector-runtime-landing
说明: Phase2 伏笔结果投影器，负责校验与 ChunkAnnotation 伏笔视图合并。
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
    校验并归一化 Phase2 伏笔结果。

    创建时间: 2026-04-23
    任务: annotation-projector-runtime-landing
    新建原因: 将 Phase2 输出校验从 multi_phase 调度层迁到 foreshadowing projector。
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
) -> ChunkAnnotation:
    """
    将 Phase2 伏笔结果投影回 ChunkAnnotation 写入视图。

    创建时间: 2026-04-23
    任务: annotation-projector-runtime-landing
    新建原因: storage 只做写入编排，伏笔字段覆盖和描述拼接由 projector 统一处理。
    """
    if foreshadowing is None:
        return annotation

    return ChunkAnnotation(
        emotional_valence=annotation.emotional_valence,
        event_type=annotation.event_type,
        pivot_moment=annotation.pivot_moment,
        cliffhanger=annotation.cliffhanger,
        chunk_summary=annotation.chunk_summary,
        has_foreshadowing=foreshadowing.has_foreshadowing,
        foreshadowing_type=foreshadowing.foreshadowing_type,
        foreshadowing_desc=(
            f"{foreshadowing.anchor_text} - {foreshadowing.anchor_reason}" if foreshadowing.has_foreshadowing else ""
        ),
        characters=annotation.characters,
        dialogues=annotation.dialogues,
    )
