"从 src/fact_graph/read/source.py 分离的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import Chapter, Paragraph


def fact_graph_read_source_read_evidence_source_1(_session, chapter_id, run_id):
    return _session.scalar(select(Chapter).where(Chapter.run_id == run_id, Chapter.chapter_id == chapter_id))


def fact_graph_read_source_read_evidence_source_2(_session, chapter_id, run_id):
    return _session.scalars(
        select(Paragraph)
        .where(Paragraph.run_id == run_id, Paragraph.chapter_id == chapter_id)
        .order_by(Paragraph.paragraph_index)
    )
