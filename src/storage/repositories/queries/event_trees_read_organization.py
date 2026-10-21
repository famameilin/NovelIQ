"event trees read organization 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import (
    Agent,
    Chapter,
    ChapterAnnotation,
    CompleteEvent,
    DiagnosisReport,
    EventParticipant,
    GraphEntity,
    NarrativeGroup,
    NarrativeLink,
    Paragraph,
)
from src.storage.repositories import narrative_records as smap


def event_trees_read_organization_load_annotations_1(_session, value_1):
    stmt = (
        select(ChapterAnnotation)
        .where(ChapterAnnotation.run_id == value_1)
        .order_by(ChapterAnnotation.created_at, ChapterAnnotation.record_id)
    )
    return _session.scalars(stmt)


def event_trees_read_organization_load_report_1(_session, value_1):
    return _session.scalars(
        select(DiagnosisReport)
        .join(Agent, Agent.id == DiagnosisReport.agent_id)
        .where(Agent.run_id == value_1)
        .order_by(DiagnosisReport.created_at.desc(), DiagnosisReport.report_id.desc())
        .limit(1)
    ).first()


def event_trees_read_organization_load_1(_session, value_1):
    return _session.scalars(select(Paragraph).where(Paragraph.run_id == value_1))


def event_trees_read_organization_load_2(_session, value_1):
    return _session.scalars(
        select(Chapter)
        .where(Chapter.run_id == value_1, Chapter.text.is_not(None))
        .order_by(Chapter.sequence, Chapter.chapter_id)
    )


def event_trees_read_organization_load_containments_1(_session, value_1):
    return _session.scalars(
        select(NarrativeLink).where(
            NarrativeLink.producer_agent_id.in_(smap.run_execution_ids(value_1)),
            NarrativeLink.contained_child_id.is_not(None),
        )
    )


def event_trees_read_organization_annotation_event_participants_1(_session, source_event_ids):
    return _session.scalars(
        select(EventParticipant)
        .where(EventParticipant.event_id.in_(source_event_ids))
        .order_by(EventParticipant.event_id, EventParticipant.participant_ordinal)
    )


def event_trees_read_organization_annotation_event_participants_2(_session, rows):
    return _session.scalars(select(GraphEntity).where(GraphEntity.entity_id.in_({row.entity_id for row in rows})))


def event_trees_read_organization_load_annotation_events_1(_session, records):
    return _session.scalars(select(CompleteEvent).where(CompleteEvent.annotation_record_id.in_(list(records))))


def event_trees_read_organization_load_organization_1(_session, producer_executions):
    return _session.scalars(
        select(NarrativeGroup)
        .where(NarrativeGroup.producer_agent_id.in_(producer_executions))
        .order_by(NarrativeGroup.group_id)
    )


def event_trees_read_organization_load_organization_2(_session, producer_executions):
    return _session.scalars(
        select(NarrativeLink)
        .where(NarrativeLink.producer_agent_id.in_(producer_executions))
        .order_by(NarrativeLink.link_id)
    )
