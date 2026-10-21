"event trees action order 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import EventForeshadowingAction


def event_trees_action_order_load_foreshadowing_actions_1(_session, annotation_events):
    return _session.scalars(
        select(EventForeshadowingAction).where(
            EventForeshadowingAction.source_event_id.in_(annotation_events)
            | EventForeshadowingAction.target_event_id.in_(annotation_events)
        )
    )
