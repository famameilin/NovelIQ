"metrics queries annotations 的具名物理读取"

from __future__ import annotations

from sqlalchemy import func, select

from src.storage.models import AnalysisAssessment


def metrics_queries_annotations_fetch_paragraph_label_counts_1(_session, record_ids):
    statement = (
        select(AnalysisAssessment.record_id, func.count().label("label_count"))
        .where(AnalysisAssessment.record_id.in_(record_ids), AnalysisAssessment.emotion.is_not(None))
        .group_by(AnalysisAssessment.record_id)
    )
    return _session.execute(statement)
