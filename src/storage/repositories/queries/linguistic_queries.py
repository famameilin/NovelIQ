"从 src/linguistic/queries.py 分离的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import AnalysisAssessment, ChapterAnnotation


def linguistic_queries_fetch_paragraph_labels_1(_session, run_id):
    return _session.execute(
        select(AnalysisAssessment.paragraph_id, AnalysisAssessment.emotion)
        .select_from(AnalysisAssessment)
        .join(ChapterAnnotation, ChapterAnnotation.record_id == AnalysisAssessment.record_id)
        .where(ChapterAnnotation.run_id == run_id, AnalysisAssessment.record_id.is_not(None))
        .order_by(AnalysisAssessment.paragraph_id)
    ).all()
