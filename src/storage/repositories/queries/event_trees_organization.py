"event trees organization 的具名物理读取"

from __future__ import annotations

from sqlalchemy import or_, select

from src.storage.models import (
    Agent,
    Chapter,
    ChapterAnnotation,
    CompleteEvent,
    DiagnosisReport,
    EventForeshadowingAction,
    EventParticipant,
    GraphEntity,
    GraphFact,
    NarrativeGroup,
    NarrativeLink,
    Paragraph,
)
from src.storage.repositories import narrative_records as smap


def event_trees_organization_published_arc_ids_1(_session, run_id):
    stmt = select(NarrativeGroup.group_id).where(NarrativeGroup.producer_agent_id.in_(smap.run_execution_ids(run_id)))
    return _session.scalars(stmt)


def event_trees_organization_run_annotation_records_1(_session, run_id):
    stmt = (
        select(ChapterAnnotation, Chapter)
        .join(
            Chapter, (Chapter.run_id == ChapterAnnotation.run_id) & (Chapter.chapter_id == ChapterAnnotation.chapter_id)
        )
        .where(ChapterAnnotation.run_id == run_id)
    )
    return _session.execute(stmt).all()


def event_trees_organization_run_foreshadowing_actions_1(_session, annotation_events):
    stmt = select(EventForeshadowingAction).where(
        or_(
            EventForeshadowingAction.source_event_id.in_(annotation_events),
            EventForeshadowingAction.target_event_id.in_(annotation_events),
        )
    )
    return _session.scalars(stmt.order_by(EventForeshadowingAction.operation_order, EventForeshadowingAction.action_id))


def event_trees_organization_require_report_1(_session, report_id):
    return _session.get(DiagnosisReport, report_id)


def event_trees_organization_require_report_2(_session, report):
    return _session.get(Agent, report.agent_id)


def event_trees_organization_parents_1(_session, value_1):
    stmt = select(NarrativeLink).where(
        NarrativeLink.producer_agent_id.in_(smap.run_execution_ids(value_1)),
        NarrativeLink.contained_child_id.is_not(None),
    )
    return _session.scalars(stmt)


def event_trees_organization_annotation_event_rows_1(_session, source_event_ids):
    return _session.scalars(
        select(EventParticipant)
        .where(EventParticipant.event_id.in_(source_event_ids))
        .order_by(EventParticipant.event_id, EventParticipant.participant_ordinal)
    )


def event_trees_organization_annotation_event_rows_2(_session, source_event_ids, value_1):
    return _session.scalars(
        select(NarrativeLink)
        .where(
            NarrativeLink.producer_agent_id.in_(smap.run_execution_ids(value_1)),
            NarrativeLink.semantic_source_event_id.is_not(None),
            NarrativeLink.semantic_target_event_id.is_not(None),
            or_(
                NarrativeLink.semantic_source_event_id.in_(source_event_ids),
                NarrativeLink.semantic_target_event_id.in_(source_event_ids),
            ),
        )
        .order_by(NarrativeLink.link_id)
    )


def event_trees_organization_annotation_event_rows_3(_session, records):
    return _session.scalars(select(CompleteEvent).where(CompleteEvent.annotation_record_id.in_(list(records))))


def event_trees_organization_annotation_event_rows_4(_session, participant_rows):
    return _session.scalars(
        select(GraphEntity).where(GraphEntity.entity_id.in_({row.entity_id for row in participant_rows}))
    )


def event_trees_organization_read_passages_1(_session, paragraph_ids, value_1):
    return _session.scalars(
        select(Paragraph)
        .where(Paragraph.run_id == value_1, Paragraph.paragraph_id.in_(paragraph_ids))
        .order_by(Paragraph.paragraph_id)
    ).all()


def event_trees_organization_validate_subject_1(_session, fact_id):
    return _session.get(GraphFact, fact_id)
