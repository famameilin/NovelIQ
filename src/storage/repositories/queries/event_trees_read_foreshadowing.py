"event trees read foreshadowing 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import CompleteEvent


def event_trees_read_foreshadowing_foreshadowing_roots_1(_session, annotation_events):
    return _session.scalars(
        select(CompleteEvent).where(
            CompleteEvent.event_id.in_(annotation_events), CompleteEvent.is_foreshadowing_root.is_(True)
        )
    )
