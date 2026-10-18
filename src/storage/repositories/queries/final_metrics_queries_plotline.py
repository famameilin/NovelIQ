"final metrics queries plotline 的具名物理读取"

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from src.storage.models import (
    ChapterAnnotation,
    CompleteEvent,
    DeclarationParticipant,
    EventDeclaration,
    EventRevision,
    Execution,
    GraphEntity,
    GraphFact,
    GraphRelation,
)


def final_metrics_queries_plotline_fetch_facts_1(_session, chapter_ids, value_1):
    participant_statement = (
        select(
            GraphFact.graph_fact_id,
            ChapterAnnotation.chapter_id.label("chapter_id"),
            Execution.execution_id.label("author_execution_id"),
            Execution.role.label("role"),
            GraphFact.operation_order,
            GraphFact.declaration_id,
            GraphFact.participant_id,
            DeclarationParticipant.entity_id.label("subject_entity_id"),
            GraphEntity.canonical_name.label("entity_name"),
            DeclarationParticipant.narrative_role,
            DeclarationParticipant.action,
            DeclarationParticipant.emotion,
        )
        .join(DeclarationParticipant, DeclarationParticipant.participant_id == GraphFact.participant_id)
        .join(GraphEntity, GraphEntity.entity_id == DeclarationParticipant.entity_id)
        .join(EventDeclaration, EventDeclaration.declaration_id == DeclarationParticipant.declaration_id)
        .join(ChapterAnnotation, ChapterAnnotation.record_id == EventDeclaration.record_id)
        .join(Execution, Execution.execution_id == ChapterAnnotation.execution_id)
        .where(
            GraphFact.participant_id.is_not(None),
            ChapterAnnotation.run_id == value_1,
            ChapterAnnotation.chapter_id.in_(chapter_ids),
        )
    )
    return _session.execute(participant_statement).mappings()


def final_metrics_queries_plotline_direct_facts(_session, run_id, chapter_ids):
    from_entity = aliased(GraphEntity)
    to_entity = aliased(GraphEntity)
    chapter_column = func.coalesce(Execution.chapter_id, GraphFact.effective_chapter_id)
    direct_statement = (
        select(
            GraphFact.graph_fact_id,
            chapter_column.label("chapter_id"),
            Execution.execution_id.label("author_execution_id"),
            Execution.role.label("role"),
            GraphFact.operation_order,
            GraphFact.entity_id,
            GraphFact.relation_id,
            GraphFact.declaration_id,
            GraphFact.plotline_subject_id,
            GraphFact.plotline_subject_title,
            GraphFact.plotline_description,
            GraphFact.plotline_before,
            GraphFact.plotline_after,
            GraphFact.description_action,
            GraphFact.description_value,
            GraphFact.representative_action,
            GraphFact.representative_value,
            GraphFact.tags_submitted,
            GraphFact.relation_change_kind,
            GraphFact.identity_kind,
            GraphFact.reason,
            GraphEntity.canonical_name.label("entity_name"),
            GraphRelation.relation_type,
            from_entity.canonical_name.label("from_entity"),
            to_entity.canonical_name.label("to_entity"),
        )
        .join(Execution, Execution.execution_id == GraphFact.direct_producer_execution_id)
        .outerjoin(GraphEntity, GraphEntity.entity_id == GraphFact.entity_id)
        .outerjoin(GraphRelation, GraphRelation.relation_id == GraphFact.relation_id)
        .outerjoin(from_entity, from_entity.entity_id == GraphRelation.from_entity_id)
        .outerjoin(to_entity, to_entity.entity_id == GraphRelation.to_entity_id)
        .where(
            GraphFact.direct_producer_execution_id.is_not(None),
            GraphFact.direct_producer_execution_id.in_(
                select(Execution.execution_id).where(Execution.run_id == run_id).correlate(None)
            ),
            GraphFact.relation_id.is_not(None)
            | GraphFact.entity_id.is_not(None)
            | GraphFact.plotline_subject_id.is_not(None),
            chapter_column.in_(chapter_ids),
        )
    )
    return _session.execute(direct_statement).mappings().all()


def final_metrics_queries_plotline_bindings(_session, run_id):
    statement = (
        select(EventRevision.declaration_id, CompleteEvent.event_id)
        .join(CompleteEvent, CompleteEvent.event_id == EventRevision.event_id)
        .where(
            EventRevision.declaration_id.is_not(None),
            CompleteEvent.producer_execution_id.in_(
                select(Execution.execution_id).where(Execution.run_id == run_id).correlate(None)
            ),
        )
    )
    return _session.execute(statement).all()
