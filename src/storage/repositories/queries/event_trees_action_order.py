"event trees action order 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import CompleteEvent, EventForeshadowingAction, EventRevision
from src.storage.repositories import narrative_records as smap


def event_trees_action_order_load_foreshadowing_actions_1(_session, declarations):
    return _session.scalars(
        select(EventForeshadowingAction).where(
            EventForeshadowingAction.source_declaration_id.in_(declarations)
            | EventForeshadowingAction.target_declaration_id.in_(declarations)
        )
    )


def event_trees_action_order_load_foreshadowing_actions_2(_session, declarations, run_id):
    return _session.scalars(
        select(EventRevision)
        .join(CompleteEvent, CompleteEvent.event_id == EventRevision.event_id)
        .where(
            EventRevision.declaration_id.in_(declarations),
            CompleteEvent.producer_execution_id.in_(smap.run_execution_ids(run_id)),
        )
    )
