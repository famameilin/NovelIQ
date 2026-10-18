"final agents annotation text search 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import Chapter, Paragraph


def final_agents_annotation_text_search_search_1(
    _session, after_chapter_sequence, before_chapter_sequence, merged, value_1
):
    metadata_statement = (
        select(Paragraph.paragraph_id, Paragraph.chapter_id)
        .join(Chapter, (Chapter.run_id == Paragraph.run_id) & (Chapter.chapter_id == Paragraph.chapter_id))
        .where(Paragraph.run_id == value_1, Paragraph.paragraph_id.in_(list(merged)))
    )
    if before_chapter_sequence is not None:
        metadata_statement = metadata_statement.where(Chapter.sequence < before_chapter_sequence)
    if after_chapter_sequence is not None:
        metadata_statement = metadata_statement.where(Chapter.sequence > after_chapter_sequence)
    return _session.execute(metadata_statement).all()
