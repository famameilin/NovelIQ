"sse persistence 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import EventOutbox

_REPLAY_BATCH = 128


def sse_persistence_replay_1(_session, statement):
    return _session.execute(statement).yield_per(_REPLAY_BATCH)


def sse_persistence_display_state_1(_session, _RESET_EVENT_TYPES, run_id):
    return _session.execute(
        select(EventOutbox.event_type, EventOutbox.emitted_bytes, EventOutbox.stream_id)
        .where(EventOutbox.run_id == run_id, EventOutbox.event_type.in_(_RESET_EVENT_TYPES))
        .order_by(EventOutbox.stream_id)
    )
