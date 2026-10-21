"event trees persistence 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import (
    Chapter,
    ChapterAnnotation,
    CompleteEvent,
)


def event_trees_persistence_annotation_event_1(_session, identifier):
    return _session.get(CompleteEvent, identifier)


def event_trees_persistence_annotation_event_2(_session, row, run_id):
    return _session.execute(
        select(ChapterAnnotation.run_id, Chapter.sequence)
        .join(
            Chapter, (Chapter.run_id == ChapterAnnotation.run_id) & (Chapter.chapter_id == ChapterAnnotation.chapter_id)
        )
        .where(ChapterAnnotation.record_id == row.annotation_record_id, ChapterAnnotation.run_id == run_id)
        .limit(1)
    ).first()
