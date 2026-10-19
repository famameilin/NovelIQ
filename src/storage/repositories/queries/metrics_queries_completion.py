"metrics queries completion 的具名物理读取"

from __future__ import annotations

from sqlalchemy import func, select

from src.storage.models import Chapter, GlobalStats


def metrics_queries_completion_is_aggregate_complete_1(_session, run_id):
    return _session.scalar(select(GlobalStats.run_id).where(GlobalStats.run_id == run_id))


def metrics_queries_completion_is_aggregate_complete_2(_session, run_id):
    return _session.execute(select(func.count()).select_from(Chapter).where(Chapter.run_id == run_id)).scalar()
