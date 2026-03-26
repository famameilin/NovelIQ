"""
运行统计相关操作

创建时间: 2026-03-17
创建者: TraeAI
任务: code-quality-refactor - 拆分stats_repository
说明: 运行状态、完成度检查等操作
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from src.storage.models import Chunk, ChunkTopic, CloudAnalysis, EmotionCurve, RhythmCurve

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def has_aggregated_data(session: Session, run_id: str) -> bool:
    """
    检查指定运行是否有聚合数据

    Args:
        session: 数据库会话
        run_id: 运行ID

    Returns:
        是否有聚合数据
    """
    emotion_count = (
        session.execute(
            select(func.count()).select_from(EmotionCurve).where(EmotionCurve.run_id == run_id)
        ).scalar()
        or 0
    )

    rhythm_count = (
        session.execute(
            select(func.count()).select_from(RhythmCurve).where(RhythmCurve.run_id == run_id)
        ).scalar()
        or 0
    )

    return emotion_count > 0 and rhythm_count > 0


def has_topic_data(session: Session, run_id: str) -> bool:
    """
    检查指定运行是否有主题数据

    Args:
        session: 数据库会话
        run_id: 运行ID

    Returns:
        是否有主题数据
    """
    count = (
        session.execute(
            select(func.count()).select_from(ChunkTopic).where(ChunkTopic.run_id == run_id)
        ).scalar()
        or 0
    )
    return count > 0


def has_diagnosis_data(session: Session, run_id: str) -> bool:
    """
    检查指定运行是否有诊断数据

    Args:
        session: 数据库会话
        run_id: 运行ID

    Returns:
        是否有诊断数据
    """
    count = (
        session.execute(
            select(func.count()).select_from(CloudAnalysis).where(CloudAnalysis.run_id == run_id)
        ).scalar()
        or 0
    )
    return count > 0


def is_aggregate_complete(session: Session, run_id: str) -> bool:
    """
    检查聚合阶段是否完成

    Args:
        session: 数据库会话
        run_id: 运行ID

    Returns:
        聚合是否完成
    """
    chunks_count = (
        session.execute(select(func.count()).select_from(Chunk).where(Chunk.run_id == run_id)).scalar() or 0
    )

    emotion_count = (
        session.execute(
            select(func.count()).select_from(EmotionCurve).where(EmotionCurve.run_id == run_id)
        ).scalar()
        or 0
    )

    rhythm_count = (
        session.execute(
            select(func.count()).select_from(RhythmCurve).where(RhythmCurve.run_id == run_id)
        ).scalar()
        or 0
    )

    return chunks_count > 0 and emotion_count >= chunks_count and rhythm_count >= chunks_count
