"从 src/agents/annotation/queries.py 分离的具名物理读取"

from __future__ import annotations

from sqlalchemy import select, text

from src.storage.models import Chapter, Paragraph


def agents_annotation_queries_init_1(_session, current_chapter_id, run_id):
    return _session.execute(
        select(Chapter.sequence).where(Chapter.run_id == run_id, Chapter.chapter_id == current_chapter_id)
    ).scalar_one_or_none()


def agents_annotation_queries_init_2(_session, run_id):
    return _session.execute(
        select(Chapter.chapter_id).where(Chapter.run_id == run_id).order_by(Chapter.sequence, Chapter.chapter_id)
    ).scalars()


def agents_annotation_queries_read_scope_1(_session):
    return _session.execute(text("SET TRANSACTION READ ONLY"))


def agents_annotation_queries_read_1(_session, paragraph_id, value_1):
    return _session.execute(
        select(Paragraph, Chapter.sequence)
        .join(Chapter, (Chapter.run_id == Paragraph.run_id) & (Chapter.chapter_id == Paragraph.chapter_id))
        .where(Paragraph.run_id == value_1, Paragraph.paragraph_id == paragraph_id)
    ).one_or_none()
