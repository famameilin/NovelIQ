"""metrics 的固定 SQL 记录查询"""

from __future__ import annotations

from sqlalchemy import func, select

from src.storage.models import AnalysisAssessment, GlobalStats


def list_output_label_counts(_session, record_ids):
    statement = (
        select(AnalysisAssessment.record_id, func.count().label("label_count"))
        .where(AnalysisAssessment.record_id.in_(record_ids), AnalysisAssessment.emotion.is_not(None))
        .group_by(AnalysisAssessment.record_id)
    )
    return _session.execute(statement)

def find_global_stats(_session, run_id):
    return _session.scalar(select(GlobalStats.run_id).where(GlobalStats.run_id == run_id))
