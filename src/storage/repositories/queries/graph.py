"""graph 的固定 SQL 记录查询"""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import aliased

from src.storage.models import (
    Agent,
    ChapterAnnotation,
    CompleteEvent,
    EventParticipant,
    FactEntityTag,
    GraphEntity,
    GraphFact,
    GraphRelation,
    SourceEvidence,
)


def list_facts_with_source_chapters(_session, valid_executions):
    return _session.execute(
        select(GraphFact, ChapterAnnotation.chapter_id)
        .join(Agent, Agent.id == GraphFact.direct_producer_agent_id)
        .outerjoin(ChapterAnnotation, ChapterAnnotation.agent_id == Agent.id)
        .where(GraphFact.direct_producer_agent_id.in_(valid_executions))
    )


def list_fact_evidence(_session, fact_chapter):
    return _session.scalars(select(SourceEvidence).where(SourceEvidence.graph_fact_id.in_(list(fact_chapter))))


def list_entities_by_ids(_session, lookup_ids):
    return _session.scalars(select(GraphEntity).where(GraphEntity.entity_id.in_(lookup_ids)))


def list_run_characters(_session, run_id):
    return _session.scalars(
        select(GraphEntity).where(GraphEntity.run_id == run_id, GraphEntity.entity_type == "character")
    )


def list_participant_entities(_session, participant_rows):
    return _session.scalars(
        select(GraphEntity).where(GraphEntity.entity_id.in_({row.entity_id for row in participant_rows}))
    )


def get_fact(_session, fact_id):
    return _session.get(GraphFact, fact_id)


def list_referenced_entities(_session, rows):
    return _session.scalars(select(GraphEntity).where(GraphEntity.entity_id.in_({row.entity_id for row in rows})))


def list_saved_participant_entities(_session, participant_rows):
    return _session.scalars(
        select(GraphEntity).where(GraphEntity.entity_id.in_({row.entity_id for row in participant_rows}))
    )


def list_participating_entity_ids(_session, run_id):
    run_executions = select(Agent.id).where(or_(Agent.run_id == run_id, Agent.run_id == run_id))
    return _session.scalars(
        select(EventParticipant.entity_id)
        .join(CompleteEvent, CompleteEvent.event_id == EventParticipant.event_id)
        .join(ChapterAnnotation, ChapterAnnotation.record_id == CompleteEvent.annotation_record_id)
        .where(ChapterAnnotation.agent_id.in_(run_executions))
    )


def list_execution_fact_tags(_session, rows):
    return _session.execute(
        select(FactEntityTag).where(FactEntityTag.graph_fact_id.in_([row.graph_fact_id for row in rows]))
    ).scalars()


def list_fact_tags_for_executions(_session, agent_ids):
    return _session.execute(
        select(FactEntityTag)
        .join(GraphFact, GraphFact.graph_fact_id == FactEntityTag.graph_fact_id)
        .where(GraphFact.direct_producer_agent_id.in_(list(agent_ids)))
    ).scalars()


def list_execution_fact_evidence(_session, rows):
    return _session.execute(
        select(SourceEvidence).where(SourceEvidence.graph_fact_id.in_([row.graph_fact_id for row in rows]))
    ).scalars()


def list_producer_facts(_session, agent_id):
    return _session.execute(
        select(GraphFact)
        .where(GraphFact.direct_producer_agent_id == agent_id)
        .order_by(GraphFact.operation_order, GraphFact.graph_fact_id)
    ).scalars()


def list_execution_facts(_session, agent_ids):
    return _session.execute(
        select(GraphFact)
        .where(GraphFact.direct_producer_agent_id.in_(list(agent_ids)))
        .order_by(GraphFact.operation_order, GraphFact.graph_fact_id)
    ).scalars()


def list_run_entities(_session, run_id):
    return _session.execute(select(GraphEntity).where(GraphEntity.run_id == run_id)).scalars()


def list_relations(_session):
    return _session.execute(select(GraphRelation)).scalars()


def list_registry_fact_tags(_session, facts):
    return _session.execute(
        select(FactEntityTag).where(FactEntityTag.graph_fact_id.in_([row.graph_fact_id for row in facts]))
    ).scalars()


def get_fact_relation(_session, fact):
    return _session.get(GraphRelation, fact.relation_id)


def list_registry_entities(_session, run_id):
    return _session.execute(select(GraphEntity).where(GraphEntity.run_id == run_id)).scalars()


def list_run_facts(_session, run_id):
    run_executions = select(Agent.id).where(or_(Agent.run_id == run_id, Agent.run_id == run_id))
    return _session.execute(
        select(GraphFact)
        .where(GraphFact.direct_producer_agent_id.in_(run_executions))
        .order_by(GraphFact.graph_fact_id)
    ).scalars()


def list_participant_changes(_session, chapter_ids, run_id):
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
            ChapterAnnotation.run_id == run_id,
            ChapterAnnotation.chapter_id.in_(chapter_ids),
        )
    )
    return _session.execute(participant_statement).mappings()


def list_direct_changes(_session, run_id, chapter_ids):
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


def list_ordered_fact_tags(_session, fact_ids):
    statement = (
        select(FactEntityTag.graph_fact_id, FactEntityTag.tag_ordinal, FactEntityTag.tag)
        .where(FactEntityTag.graph_fact_id.in_(fact_ids))
        .order_by(FactEntityTag.graph_fact_id, FactEntityTag.tag_ordinal)
    )
    return _session.execute(statement).all()
