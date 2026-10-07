"""所属领域的产物完整性查询，供恢复编排调用"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.storage.models import (
    Chapter,
    GlobalStats,
)


def is_aggregate_complete(session: Session, run_id: str) -> bool:
    """检查聚合阶段是否完成（chapters+global_stats 均存在）。Args: session/run_id；Returns: 是否完成。"""
    chapters_count = (
        session.execute(select(func.count()).select_from(Chapter).where(Chapter.run_id == run_id)).scalar() or 0
    )

    # 2026-08-14 M8b：聚合阶段唯一落库产物是 global_stats（chunk_curves 已下线），
    # 完成判定改以 global_stats 存在为准
    stats_count = (
        session.execute(select(func.count()).select_from(GlobalStats).where(GlobalStats.run_id == run_id)).scalar() or 0
    )

    return chapters_count > 0 and stats_count > 0
