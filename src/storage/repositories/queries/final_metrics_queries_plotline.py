"final metrics queries plotline 的具名物理读取"

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from src.storage.models import (
    Agent,
    ChapterAnnotation,
    CompleteEvent,
    EventParticipant,
    GraphEntity,
    GraphFact,
    GraphRelation,
)


def final_metrics_queries_plotline_fetch_facts_1(_session, chapter_ids, value_1):
    participant_statement = (
        select(
            GraphFact.graph_fact_id,
            ChapterAnnotation.chapter_id.label("chapter_id"),
            Agent.id.label("author_agent_id"),
            Agent.type.label("role"),
            GraphFact.operation_order,
            GraphFact.event_id,
            GraphFact.participant_id,
            EventParticipant.entity_id.label("subject_entity_id"),
            GraphEntity.canonical_name.label("entity_name"),
            EventParticipant.narrative_role,
            EventParticipant.action,
            EventParticipant.emotion,
        )
        .join(EventParticipant, EventParticipant.participant_id == GraphFact.participant_id)
        .join(GraphEntity, GraphEntity.entity_id == EventParticipant.entity_id)
        .join(CompleteEvent, CompleteEvent.event_id == EventParticipant.event_id)
        .join(ChapterAnnotation, ChapterAnnotation.record_id == CompleteEvent.annotation_record_id)
        .join(Agent, Agent.id == ChapterAnnotation.agent_id)
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
    chapter_column = func.coalesce(ChapterAnnotation.chapter_id, GraphFact.effective_chapter_id)
    direct_statement = (
        select(
            GraphFact.graph_fact_id,
            chapter_column.label("chapter_id"),
            Agent.id.label("author_agent_id"),
            Agent.type.label("role"),
            GraphFact.operation_order,
            GraphFact.entity_id,
            GraphFact.relation_id,
            GraphFact.event_id,
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
        .join(Agent, Agent.id == GraphFact.direct_producer_agent_id)
        .outerjoin(ChapterAnnotation, ChapterAnnotation.agent_id == Agent.id)
        .outerjoin(GraphEntity, GraphEntity.entity_id == GraphFact.entity_id)
        .outerjoin(GraphRelation, GraphRelation.relation_id == GraphFact.relation_id)
        .outerjoin(from_entity, from_entity.entity_id == GraphRelation.from_entity_id)
        .outerjoin(to_entity, to_entity.entity_id == GraphRelation.to_entity_id)
        .where(
            GraphFact.direct_producer_agent_id.is_not(None),
            GraphFact.direct_producer_agent_id.in_(select(Agent.id).where(Agent.run_id == run_id).correlate(None)),
            GraphFact.relation_id.is_not(None)
            | GraphFact.entity_id.is_not(None)
            | GraphFact.plotline_subject_id.is_not(None),
            chapter_column.in_(chapter_ids),
        )
    )
    return _session.execute(direct_statement).mappings().all()
