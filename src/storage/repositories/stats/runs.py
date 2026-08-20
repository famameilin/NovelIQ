"""
运行统计相关操作

运行状态、完成度检查等操作

2026-08-14 M8b：ChunkCurve 引用移除——聚合完成度改按 global_stats 判定
（曲线事实源为 paragraph_curves）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from src.storage.models import Chapter, CloudAnalysis, GlobalStats, ParagraphTopic

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
    # 2026-08-14 M8b：聚合唯一落库产物为 global_stats（chunk_curves 已下线）
    stats_count = (
        session.execute(select(func.count()).select_from(GlobalStats).where(GlobalStats.run_id == run_id)).scalar()
        or 0
    )

    return stats_count > 0


def has_topic_data(session: Session, run_id: str) -> bool:
    """
    检查指定运行是否有主题数据（段落粒度，设计 §11.1）

    主题建模已段落化，chunk_topics 不再写入；完成判定改查 paragraph_topics。

    Args:
        session: 数据库会话
        run_id: 运行ID

    Returns:
        是否有主题数据
    """
    count = (
        session.execute(
            select(func.count()).select_from(ParagraphTopic).where(ParagraphTopic.run_id == run_id)
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
    latest_row = session.execute(
        select(CloudAnalysis).where(CloudAnalysis.run_id == run_id).order_by(CloudAnalysis.id.desc()).limit(1)
    ).scalar_one_or_none()
    if latest_row is None:
        return False
    return True


def is_aggregate_complete(session: Session, run_id: str) -> bool:
    """
    检查聚合阶段是否完成

    Args:
        session: 数据库会话
        run_id: 运行ID

    Returns:
        聚合是否完成
    """
    chapters_count = session.execute(
        select(func.count()).select_from(Chapter).where(Chapter.run_id == run_id)
    ).scalar() or 0

    # 2026-08-14 M8b：聚合阶段唯一落库产物是 global_stats（chunk_curves 已下线），
    # 完成判定改以 global_stats 存在为准
    stats_count = (
        session.execute(select(func.count()).select_from(GlobalStats).where(GlobalStats.run_id == run_id)).scalar()
        or 0
    )

    return chapters_count > 0 and stats_count > 0
