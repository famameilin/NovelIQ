"agents annotation agent 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import (
    Agent,
    AnalysisAssessment,
    Case,
    Chapter,
    ChapterAnnotation,
    DeclarationParticipant,
    DialogueRecord,
    EventDeclaration,
    EventForeshadowingAction,
    GraphEntity,
    GraphFact,
    GraphRelation,
)


def agents_annotation_agent_save_1(_session, annotation_id):
    return _session.get(ChapterAnnotation, annotation_id)


def agents_annotation_agent_save_2(_session, annotation_id):
    return _session.get(ChapterAnnotation, annotation_id)


def agents_annotation_agent_recover_1(_session, value_1):
    return _session.execute(
        select(
            ChapterAnnotation.record_id,
            ChapterAnnotation.agent_id,
            ChapterAnnotation.role,
            ChapterAnnotation.chapter_id,
            Chapter.sequence,
        )
        .join(
            Chapter, (Chapter.run_id == ChapterAnnotation.run_id) & (Chapter.chapter_id == ChapterAnnotation.chapter_id)
        )
        .where(ChapterAnnotation.run_id == value_1)
    )


def agents_annotation_agent_query_1(_session, execution_invocation_id):
    return _session.get(Agent, execution_invocation_id)


def agents_annotation_agent_query_2(_session, annotation_id):
    return _session.get(ChapterAnnotation, annotation_id)


def agents_annotation_agent_query_3(_session):
    return _session.scalars(select(GraphFact).where(GraphFact.participant_id.is_not(None)))


def agents_annotation_agent_query_4(_session, message_invocation_id):
    return _session.scalars(
        select(GraphFact.relation_id).where(
            GraphFact.direct_producer_agent_id == message_invocation_id, GraphFact.relation_id.is_not(None)
        )
    )


def agents_annotation_agent_query_5(_session, participant_fact):
    return _session.get(DeclarationParticipant, participant_fact.participant_id)


def agents_annotation_agent_query_6(_session, participant):
    return _session.get(EventDeclaration, participant.declaration_id)


def agents_annotation_agent_query_7(_session, participant):
    return _session.get(GraphEntity, participant.entity_id)


def agents_annotation_agent_query_8(_session, actual_relation_ids):
    return _session.scalars(select(GraphRelation).where(GraphRelation.relation_id.in_(actual_relation_ids)))


def agents_annotation_agent_query_9(_session, annotation_id):
    return _session.scalars(select(AnalysisAssessment).where(AnalysisAssessment.record_id == annotation_id))


def agents_annotation_agent_query_10(_session, message_invocation_id):
    return _session.scalars(
        select(EventForeshadowingAction).where(EventForeshadowingAction.producer_agent_id == message_invocation_id)
    )


def agents_annotation_agent_query_11(_session, identifier):
    return _session.get(Case, identifier)


def agents_annotation_agent_query_12(_session, message_invocation_id):
    return _session.scalars(select(DialogueRecord).where(DialogueRecord.creation_agent_id == message_invocation_id))
