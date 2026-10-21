"event trees trees 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select, text

from src.storage.models import (
    ChapterAnnotation,
    CompleteEvent,
    EventForeshadowingAction,
    EventParticipant,
    GraphEntity,
    NarrativeLink,
)


def event_trees_trees_save_work_1(_session, value_1):
    return _session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"event_trees:{value_1}"}
    )


def event_trees_trees_save_work_2(_session, annotation_id):
    return _session.get(ChapterAnnotation, annotation_id)


def event_trees_trees_save_work_3(_session, action):
    return _session.get(CompleteEvent, action["root_event_id"])


def event_trees_trees_save_work_4(_session, endpoint_id):
    return _session.get(CompleteEvent, endpoint_id)


def event_trees_trees_discard_storage_1(_session, execution_ids):
    return _session.execute(
        select(CompleteEvent.event_id).where(
            CompleteEvent.annotation_record_id.in_(
                select(ChapterAnnotation.record_id).where(ChapterAnnotation.agent_id.in_(sorted(execution_ids)))
            )
        )
    ).scalars()


def event_trees_trees_load_saved_work_1(_session, annotation_id):
    return _session.get(ChapterAnnotation, annotation_id)


def event_trees_trees_load_saved_work_2(_session, annotation_id):
    return _session.scalars(select(CompleteEvent).where(CompleteEvent.annotation_record_id == annotation_id))


def event_trees_trees_load_saved_work_3(_session, source_event_ids):
    return _session.scalars(
        select(EventParticipant)
        .where(EventParticipant.event_id.in_(source_event_ids))
        .order_by(EventParticipant.event_id, EventParticipant.participant_ordinal)
    )


def event_trees_trees_load_saved_work_4(_session, agent_id):
    return _session.scalars(
        select(EventForeshadowingAction).where(EventForeshadowingAction.producer_agent_id == agent_id)
    )


def event_trees_trees_load_saved_work_5(_session, agent_id):
    return _session.scalars(
        select(NarrativeLink).where(
            NarrativeLink.producer_agent_id == agent_id,
        )
    )


def event_trees_trees_load_saved_work_6(_session, participant_rows):
    return _session.scalars(
        select(GraphEntity).where(GraphEntity.entity_id.in_({row.entity_id for row in participant_rows}))
    )
