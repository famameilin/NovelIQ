"workflows annotate 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import Chapter, Paragraph


def workflows_annotate_load_work_1(_session, run_id):
    return (
        _session.execute(select(Chapter).where(Chapter.run_id == run_id).order_by(Chapter.sequence, Chapter.chapter_id))
        .scalars()
        .all()
    )


def workflows_annotate_load_work_2(_session, chapter, run_id):
    return (
        _session.execute(
            select(Paragraph)
            .where(Paragraph.run_id == run_id, Paragraph.chapter_id == chapter.chapter_id)
            .order_by(Paragraph.paragraph_index)
        )
        .scalars()
        .all()
    )
