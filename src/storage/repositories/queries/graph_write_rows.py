"fact graph graph 的具名物理读取"

from __future__ import annotations

from sqlalchemy import or_, select, text

from src.storage.models import (
    Agent,
    AnalysisAssessment,
    ChapterAnnotation,
    CompleteEvent,
    DiagnosisReport,
    DialogueRecord,
    EventParticipant,
    GraphEntity,
    GraphFact,
    GraphRelation,
)


def lock_entity_registration(_session, run_id):
    return _session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"fact_graph:{run_id}"}
    )


def get_registered_entity(_session, identifier):
    return _session.get(GraphEntity, identifier)


def lock_fact_contribution(_session, run_id):
    return _session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"fact_graph:{run_id}"}
    )


def get_producer(_session, frozen_agent_id):
    return _session.get(Agent, frozen_agent_id)


def find_producer_fact(_session, agent_id):
    return _session.execute(
        select(GraphFact.graph_fact_id).where(GraphFact.direct_producer_agent_id == agent_id).limit(1)
    ).scalar_one_or_none()


def get_fact_entity(_session, entity_id):
    return _session.get(GraphEntity, entity_id)


def get_relation(_session, identifier):
    return _session.get(GraphRelation, identifier)


def list_relation_endpoints(_session, live_relations):
    return _session.execute(
        select(GraphRelation.from_entity_id, GraphRelation.to_entity_id).where(
            GraphRelation.relation_id.in_(live_relations)
        )
    )


def list_fact_entity_ids(_session, run_id):
    run_executions = select(Agent.id).where(or_(Agent.run_id == run_id, Agent.run_id == run_id))
    return _session.scalars(
        select(GraphFact.entity_id).where(
            GraphFact.direct_producer_agent_id.in_(run_executions), GraphFact.entity_id.is_not(None)
        )
    )


def list_fact_relation_ids(_session, run_id):
    run_executions = select(Agent.id).where(or_(Agent.run_id == run_id, Agent.run_id == run_id))
    return _session.scalars(
        select(GraphFact.relation_id).where(
            GraphFact.direct_producer_agent_id.in_(run_executions), GraphFact.relation_id.is_not(None)
        )
    )


def list_participant_entity_ids(_session, run_id):
    run_executions = select(Agent.id).where(or_(Agent.run_id == run_id, Agent.run_id == run_id))
    return _session.scalars(
        select(EventParticipant.entity_id)
        .join(CompleteEvent, CompleteEvent.event_id == EventParticipant.event_id)
        .join(ChapterAnnotation, ChapterAnnotation.record_id == CompleteEvent.annotation_record_id)
        .where(ChapterAnnotation.agent_id.in_(run_executions))
    )


def list_speaker_entity_ids(_session, run_id):
    run_executions = select(Agent.id).where(or_(Agent.run_id == run_id, Agent.run_id == run_id))
    return _session.scalars(
        select(DialogueRecord.speaker_entity_id).where(
            DialogueRecord.creation_agent_id.in_(run_executions), DialogueRecord.speaker_entity_id.is_not(None)
        )
    )


def list_cast_entity_ids(_session, run_id):
    run_executions = select(Agent.id).where(or_(Agent.run_id == run_id, Agent.run_id == run_id))
    return _session.scalars(
        select(AnalysisAssessment.cast_entity_id)
        .join(ChapterAnnotation, ChapterAnnotation.record_id == AnalysisAssessment.record_id, isouter=True)
        .where(
            ChapterAnnotation.agent_id.in_(run_executions)
            | AnalysisAssessment.report_id.in_(
                select(DiagnosisReport.report_id)
                .join(Agent, Agent.id == DiagnosisReport.agent_id)
                .where(Agent.run_id == run_id)
            ),
            AnalysisAssessment.cast_entity_id.is_not(None),
        )
    )


def list_scored_entity_ids(_session, run_id):
    run_executions = select(Agent.id).where(or_(Agent.run_id == run_id, Agent.run_id == run_id))
    return _session.scalars(
        select(AnalysisAssessment.scored_entity_id)
        .join(ChapterAnnotation, ChapterAnnotation.record_id == AnalysisAssessment.record_id, isouter=True)
        .where(
            ChapterAnnotation.agent_id.in_(run_executions)
            | AnalysisAssessment.report_id.in_(
                select(DiagnosisReport.report_id)
                .join(Agent, Agent.id == DiagnosisReport.agent_id)
                .where(Agent.run_id == run_id)
            ),
            AnalysisAssessment.scored_entity_id.is_not(None),
        )
    )
























