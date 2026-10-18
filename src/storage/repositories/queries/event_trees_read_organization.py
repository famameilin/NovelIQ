"event trees read organization 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import (
    Chapter,
    ChapterAnnotation,
    DeclarationParticipant,
    DiagnosisReport,
    EventDeclaration,
    EventRevision,
    Execution,
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
        .join(Execution, Execution.execution_id == DiagnosisReport.session_id)
        .where(Execution.session_run_id == value_1)
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


def event_trees_read_organization_load_events_1(_session, value_1):
    return _session.scalar(select(Execution.execution_id).where(Execution.session_run_id == value_1))


def event_trees_read_organization_load_containments_1(_session, value_1):
    return _session.scalars(
        select(NarrativeLink).where(
            NarrativeLink.producer_execution_id.in_(smap.run_execution_ids(value_1)),
            NarrativeLink.contained_child_id.is_not(None),
        )
    )


def event_trees_read_organization_declaration_participants_1(_session, declaration_ids):
    return _session.scalars(
        select(DeclarationParticipant)
        .where(DeclarationParticipant.declaration_id.in_(declaration_ids))
        .order_by(DeclarationParticipant.declaration_id, DeclarationParticipant.participant_ordinal)
    )


def event_trees_read_organization_declaration_participants_2(_session, rows):
    return _session.scalars(select(GraphEntity).where(GraphEntity.entity_id.in_({row.entity_id for row in rows})))


def event_trees_read_organization_load_declarations_1(_session, records):
    return _session.scalars(select(EventDeclaration).where(EventDeclaration.record_id.in_(list(records))))


def event_trees_read_organization_load_revisions_1(_session, event_ids):
    return _session.scalars(
        select(EventRevision)
        .where(EventRevision.event_id.in_(event_ids))
        .order_by(EventRevision.event_id, EventRevision.stage_index)
    )


def event_trees_read_organization_load_organization_1(_session, producer_executions):
    return _session.scalars(
        select(NarrativeGroup)
        .where(NarrativeGroup.producer_execution_id.in_(producer_executions))
        .order_by(NarrativeGroup.group_id)
    )


def event_trees_read_organization_load_organization_2(_session, producer_executions):
    return _session.scalars(
        select(NarrativeLink)
        .where(NarrativeLink.producer_execution_id.in_(producer_executions))
        .order_by(NarrativeLink.link_id)
    )
