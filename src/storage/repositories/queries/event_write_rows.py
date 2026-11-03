"event trees trees 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select, text

from src.storage.models import (
    ChapterAnnotation,
    CompleteEvent,
)


def lock_run(_session, run_id):
    return _session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"event_trees:{run_id}"}
    )


def get_output(_session, annotation_id):
    return _session.get(ChapterAnnotation, annotation_id)


def get_action_source(_session, action):
    return _session.get(CompleteEvent, action["source_event_id"])


def get_endpoint(_session, endpoint_id):
    return _session.get(CompleteEvent, endpoint_id)


def list_execution_event_ids(_session, execution_ids):
    return _session.execute(
        select(CompleteEvent.event_id).where(
            CompleteEvent.annotation_record_id.in_(
                select(ChapterAnnotation.record_id).where(ChapterAnnotation.agent_id.in_(sorted(execution_ids)))
            )
        )
    ).scalars()












