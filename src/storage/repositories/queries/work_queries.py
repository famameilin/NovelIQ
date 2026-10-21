"work queries 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import AnalysisAssessment, CompleteEvent, DialogueRecord, EventParticipant, Paragraph


def work_queries_paragraph_labels_1(_session, record_ids):
    return _session.execute(
        select(AnalysisAssessment.record_id, AnalysisAssessment.paragraph_id, AnalysisAssessment.emotion)
        .where(AnalysisAssessment.record_id.in_(record_ids))
        .order_by(AnalysisAssessment.record_id, AnalysisAssessment.paragraph_id)
    )


def work_queries_annotation_event_projections_1(_session, annotation_events):
    return _session.scalars(
        select(EventParticipant)
        .where(EventParticipant.event_id.in_([item.event_id for item in annotation_events]))
        .order_by(EventParticipant.event_id, EventParticipant.participant_ordinal)
    )


def work_queries_annotation_event_projections_2(_session, record_ids):
    return _session.scalars(
        select(CompleteEvent)
        .where(CompleteEvent.annotation_record_id.in_(record_ids))
        .order_by(CompleteEvent.created_at, CompleteEvent.event_id)
    )


def work_queries_dialogue_projections_1(_session, execution_ids):
    return _session.scalars(
        select(DialogueRecord)
        .where(DialogueRecord.creation_agent_id.in_(execution_ids))
        .order_by(DialogueRecord.creation_agent_id, DialogueRecord.start_char, DialogueRecord.candidate_key)
    )


def work_queries_character_observations_1(_session, record_by_annotation_event):
    return _session.scalars(
        select(EventParticipant)
        .where(EventParticipant.event_id.in_(list(record_by_annotation_event)))
        .order_by(EventParticipant.event_id, EventParticipant.participant_ordinal)
    )


def work_queries_character_observations_2(_session, record_ids):
    return _session.execute(
        select(CompleteEvent.event_id, CompleteEvent.annotation_record_id).where(
            CompleteEvent.annotation_record_id.in_(record_ids)
        )
    ).all()


def work_queries_paragraph_record(_session, run_id, paragraph_id):
    return _session.scalar(select(Paragraph).where(Paragraph.run_id == run_id, Paragraph.paragraph_id == paragraph_id))
