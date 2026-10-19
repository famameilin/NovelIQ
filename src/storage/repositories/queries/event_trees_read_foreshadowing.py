"event trees read foreshadowing 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import CompleteEvent, EventDeclaration, EventDeclarationBinding
from src.storage.repositories import narrative_records as smap


def event_trees_read_foreshadowing_foreshadowing_roots_1(_session, declarations):
    return _session.scalars(
        select(EventDeclaration).where(
            EventDeclaration.declaration_id.in_(declarations), EventDeclaration.is_foreshadowing_root.is_(True)
        )
    )


def event_trees_read_foreshadowing_bound_events_1(_session, declaration_ids, run_id):
    return _session.scalars(
        select(EventDeclarationBinding)
        .join(CompleteEvent, CompleteEvent.event_id == EventDeclarationBinding.event_id)
        .where(
            EventDeclarationBinding.declaration_id.in_(declaration_ids),
            CompleteEvent.producer_agent_id.in_(smap.run_execution_ids(run_id)),
        )
    )
