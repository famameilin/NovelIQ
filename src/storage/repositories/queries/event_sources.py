"event trees persistence 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import (
    Chapter,
    ChapterAnnotation,
    CompleteEvent,
)


def get_event(_session, identifier):
    return _session.get(CompleteEvent, identifier)


def get_annotation_chapter(_session, row, run_id):
    return _session.execute(
        select(ChapterAnnotation.run_id, Chapter.sequence)
        .join(
            Chapter, (Chapter.run_id == ChapterAnnotation.run_id) & (Chapter.chapter_id == ChapterAnnotation.chapter_id)
        )
        .where(ChapterAnnotation.record_id == row.annotation_record_id, ChapterAnnotation.run_id == run_id)
        .limit(1)
    ).first()
