"event trees action order 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import CompleteEvent, EventDeclarationBinding, EventForeshadowingAction
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
        select(EventDeclarationBinding)
        .join(CompleteEvent, CompleteEvent.event_id == EventDeclarationBinding.event_id)
        .where(
            EventDeclarationBinding.declaration_id.in_(declarations),
            CompleteEvent.producer_agent_id.in_(smap.run_execution_ids(run_id)),
        )
    )
