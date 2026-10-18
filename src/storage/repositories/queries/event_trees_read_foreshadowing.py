"从 src/event_trees/read/foreshadowing.py 分离的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import CompleteEvent, EventDeclaration, EventRevision
from src.storage.repositories import narrative_records as smap


def event_trees_read_foreshadowing_foreshadowing_roots_1(_session, declarations):
    return _session.scalars(
        select(EventDeclaration).where(
            EventDeclaration.declaration_id.in_(declarations), EventDeclaration.is_foreshadowing_root.is_(True)
        )
    )


def event_trees_read_foreshadowing_bound_events_1(_session, declaration_ids, run_id):
    return _session.scalars(
        select(EventRevision)
        .join(CompleteEvent, CompleteEvent.event_id == EventRevision.event_id)
        .where(
            EventRevision.declaration_id.in_(declaration_ids),
            CompleteEvent.producer_execution_id.in_(smap.run_execution_ids(run_id)),
        )
    )
