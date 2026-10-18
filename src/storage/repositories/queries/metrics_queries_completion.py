"metrics queries completion 的具名物理读取"

from __future__ import annotations

from sqlalchemy import func, select

from src.storage.models import AnalysisRun, Chapter


def metrics_queries_completion_is_aggregate_complete_1(_session, run_id):
    return _session.scalar(select(AnalysisRun.aggregate_completed_at).where(AnalysisRun.run_id == run_id))


def metrics_queries_completion_is_aggregate_complete_2(_session, run_id):
    return _session.execute(select(func.count()).select_from(Chapter).where(Chapter.run_id == run_id)).scalar()
