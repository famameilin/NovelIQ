"linguistic completion 的具名物理读取"

from __future__ import annotations

from sqlalchemy import func, select

from src.storage.models import Paragraph, ParagraphMetric


def linguistic_completion_is_linguistic_complete_1(_session, run_id):
    return (
        _session.execute(
            select(
                func.count(Paragraph.paragraph_id).label("total"),
                func.count(ParagraphMetric.paragraph_id)
                .filter(ParagraphMetric.linguistic_completed_at.is_not(None))
                .label("completed"),
            )
            .select_from(Paragraph)
            .outerjoin(
                ParagraphMetric,
                (ParagraphMetric.run_id == Paragraph.run_id) & (ParagraphMetric.paragraph_id == Paragraph.paragraph_id),
            )
            .where(Paragraph.run_id == run_id)
        )
        .mappings()
        .one()
    )
