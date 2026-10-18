"从 src/event_trees/persistence.py 分离的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import (
    Chapter,
    ChapterAnnotation,
    CompleteEvent,
    EventDeclaration,
    EventRevision,
)
from src.storage.repositories import narrative_records as smap


def event_trees_persistence_discard_declaration_contributions_1(_session, declaration_ids, run_id):
    return _session.scalar(
        select(EventRevision.declaration_id)
        .join(CompleteEvent, CompleteEvent.event_id == EventRevision.event_id)
        .where(
            EventRevision.declaration_id.in_(declaration_ids),
            CompleteEvent.producer_execution_id.in_(smap.run_execution_ids(run_id)),
        )
        .limit(1)
    )


def event_trees_persistence_declaration_1(_session, identifier):
    return _session.get(EventDeclaration, identifier)


def event_trees_persistence_declaration_2(_session, row, run_id):
    return _session.execute(
        select(ChapterAnnotation.run_id, Chapter.sequence)
        .join(
            Chapter, (Chapter.run_id == ChapterAnnotation.run_id) & (Chapter.chapter_id == ChapterAnnotation.chapter_id)
        )
        .where(ChapterAnnotation.record_id == row.record_id, ChapterAnnotation.run_id == run_id)
        .limit(1)
    ).first()
