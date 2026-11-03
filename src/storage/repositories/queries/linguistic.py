"""linguistic 的固定 SQL 记录查询"""

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import AnalysisAssessment, ChapterAnnotation
from src.storage.records.values import NamedRecord


def get_completion_counts(_session, run_id):
    from src.storage.repositories.queries.linguistic_statistics import get_statistics_completion_counts

    return NamedRecord(get_statistics_completion_counts(_session, run_id))


def list_paragraph_labels(_session, run_id):
    return _session.execute(
        select(AnalysisAssessment.paragraph_id, AnalysisAssessment.emotion)
        .select_from(AnalysisAssessment)
        .join(ChapterAnnotation, ChapterAnnotation.record_id == AnalysisAssessment.record_id)
        .where(ChapterAnnotation.run_id == run_id, AnalysisAssessment.record_id.is_not(None))
        .order_by(AnalysisAssessment.paragraph_id)
    ).all()
