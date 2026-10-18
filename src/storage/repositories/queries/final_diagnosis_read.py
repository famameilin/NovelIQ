"final diagnosis read 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import (
    CompleteEvent,
    EventRevision,
)
from src.storage.repositories.narrative_records import run_execution_ids


def final_diagnosis_read_declaration_bindings_1(_session, run_id):
    stmt = (
        select(EventRevision.declaration_id, EventRevision.event_id)
        .join(CompleteEvent, CompleteEvent.event_id == EventRevision.event_id)
        .where(
            EventRevision.declaration_id.is_not(None),
            CompleteEvent.producer_execution_id.in_(run_execution_ids(run_id)),
        )
    )
    return _session.execute(stmt)
