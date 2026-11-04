"""events 的固定 SQL 记录查询"""

from __future__ import annotations

from sqlalchemy import or_, select

from src.storage.models import (
    CompleteEvent,
    EventForeshadowingAction,
    EventParticipant,
    NarrativeGroup,
    NarrativeLink,
    SourceEvidence,
)
from src.storage.repositories import narrative_records as smap
from src.storage.repositories.narrative_records import run_execution_ids


def list_events_for_outputs(_session, records_by_record):
    return _session.scalars(
        select(CompleteEvent).where(CompleteEvent.annotation_record_id.in_(list(records_by_record)))
    )


def list_event_evidence(_session, source_event_ids):
    return _session.scalars(select(SourceEvidence).where(SourceEvidence.complete_event_id.in_(source_event_ids)))


def list_event_participants(_session, source_event_ids):
    return _session.scalars(select(EventParticipant).where(EventParticipant.event_id.in_(source_event_ids)))


def list_related_foreshadowing_actions(_session, annotation_events):
    return _session.scalars(
        select(EventForeshadowingAction).where(
            EventForeshadowingAction.source_event_id.in_(annotation_events)
            | EventForeshadowingAction.target_event_id.in_(annotation_events)
        )
    )


def list_ordered_foreshadowing_actions(_session, annotation_events):
    stmt = select(EventForeshadowingAction).where(
        or_(
            EventForeshadowingAction.source_event_id.in_(annotation_events),
            EventForeshadowingAction.target_event_id.in_(annotation_events),
        )
    )
    return _session.scalars(stmt.order_by(EventForeshadowingAction.operation_order, EventForeshadowingAction.action_id))


def list_queue_references(_session, run_id):
    stmt = select(NarrativeLink).where(
        NarrativeLink.producer_agent_id.in_(smap.run_execution_ids(run_id)),
        NarrativeLink.child_tree_id.is_not(None),
    )
    return _session.scalars(stmt)


def list_queue_links(_session, run_id):
    return _session.scalars(select(NarrativeLink).where(
        NarrativeLink.producer_agent_id.in_(smap.run_execution_ids(run_id)),
        or_(NarrativeLink.tree_id.is_not(None), NarrativeLink.parent_tree_id.is_not(None)),
    ).order_by(NarrativeLink.tree_id, NarrativeLink.position, NarrativeLink.link_id))


def list_ordered_participants(_session, source_event_ids):
    return _session.scalars(
        select(EventParticipant)
        .where(EventParticipant.event_id.in_(source_event_ids))
        .order_by(EventParticipant.event_id, EventParticipant.participant_ordinal)
    )


def list_foreshadowing_roots(_session, annotation_events):
    return _session.scalars(
        select(CompleteEvent).where(
            CompleteEvent.event_id.in_(annotation_events), CompleteEvent.is_foreshadowing_root.is_(True)
        )
    )



def list_participants_by_ordinal(_session, source_event_ids):
    return _session.scalars(
        select(EventParticipant)
        .where(EventParticipant.event_id.in_(source_event_ids))
        .order_by(EventParticipant.event_id, EventParticipant.participant_ordinal)
    )


def list_execution_groups(_session, producer_executions):
    return _session.scalars(
        select(NarrativeGroup)
        .where(NarrativeGroup.producer_agent_id.in_(producer_executions), NarrativeGroup.kind == "outcome")
        .order_by(NarrativeGroup.group_id)
    )


def list_execution_trees(_session, producer_executions):
    return _session.scalars(
        select(NarrativeGroup)
        .where(NarrativeGroup.producer_agent_id.in_(producer_executions), NarrativeGroup.kind == "tree")
        .order_by(NarrativeGroup.group_id)
    )


def list_execution_links(_session, producer_executions):
    return _session.scalars(
        select(NarrativeLink)
        .where(NarrativeLink.producer_agent_id.in_(producer_executions))
        .order_by(NarrativeLink.link_id)
    )


def list_output_events(_session, annotation_id):
    return _session.scalars(select(CompleteEvent).where(CompleteEvent.annotation_record_id == annotation_id))


def list_saved_participants(_session, source_event_ids):
    return _session.scalars(
        select(EventParticipant)
        .where(EventParticipant.event_id.in_(source_event_ids))
        .order_by(EventParticipant.event_id, EventParticipant.participant_ordinal)
    )


def list_execution_actions(_session, agent_id):
    return _session.scalars(
        select(EventForeshadowingAction).where(EventForeshadowingAction.producer_agent_id == agent_id)
    )


def list_producer_links(_session, agent_id):
    return _session.scalars(
        select(NarrativeLink).where(
            NarrativeLink.producer_agent_id == agent_id,
        )
    )


def find_run_event_id(_session, run_id):
    return _session.scalar(
        select(CompleteEvent.event_id).where(CompleteEvent.producer_agent_id.in_(run_execution_ids(run_id))).limit(1)
    )


def list_annotation_participants(_session, annotation_events):
    return _session.scalars(
        select(EventParticipant)
        .where(EventParticipant.event_id.in_([item.event_id for item in annotation_events]))
        .order_by(EventParticipant.event_id, EventParticipant.participant_ordinal)
    )


def list_ordered_output_events(_session, record_ids):
    return _session.scalars(
        select(CompleteEvent)
        .where(CompleteEvent.annotation_record_id.in_(record_ids))
        .order_by(CompleteEvent.created_at, CompleteEvent.event_id)
    )


def list_character_observations(_session, record_by_annotation_event):
    return _session.scalars(
        select(EventParticipant)
        .where(EventParticipant.event_id.in_(list(record_by_annotation_event)))
        .order_by(EventParticipant.event_id, EventParticipant.participant_ordinal)
    )


def list_output_event_ids(_session, record_ids):
    return _session.execute(
        select(CompleteEvent.event_id, CompleteEvent.annotation_record_id).where(
            CompleteEvent.annotation_record_id.in_(record_ids)
        )
    ).all()
