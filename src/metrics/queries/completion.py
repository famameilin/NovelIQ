"""所属领域的产物完整性查询，供恢复编排调用

2026-10-16 全库 3NF 改造：独立 global_stats 表退场，全书统计并入
analysis_runs 具名列；聚合阶段完成事实由 analysis_runs.aggregate_completed_at
表达（不靠某一统计列非空，avg_mtld 允许已算但为 NULL）。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.storage.models import AnalysisRun, Chapter


def is_aggregate_complete(session: Session, run_id: str) -> bool:
    """检查聚合阶段是否完成（章节存在且正式聚合完成事实非空）。Args: session/run_id；Returns: 是否完成。"""
    chapters_count = (
        session.execute(select(func.count()).select_from(Chapter).where(Chapter.run_id == run_id)).scalar() or 0
    )
    aggregate_completed_at = session.scalar(
        select(AnalysisRun.aggregate_completed_at).where(AnalysisRun.run_id == run_id)
    )
    return chapters_count > 0 and aggregate_completed_at is not None
