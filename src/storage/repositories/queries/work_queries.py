"从 src/work/queries.py 分离的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import AnalysisAssessment, DeclarationParticipant, DialogueRecord, EventDeclaration, Paragraph


def work_queries_paragraph_labels_1(_session, record_ids):
    return _session.execute(
        select(AnalysisAssessment.record_id, AnalysisAssessment.paragraph_id, AnalysisAssessment.emotion)
        .where(AnalysisAssessment.record_id.in_(record_ids))
        .order_by(AnalysisAssessment.record_id, AnalysisAssessment.paragraph_id)
    )


def work_queries_declaration_projections_1(_session, declarations):
    return _session.scalars(
        select(DeclarationParticipant)
        .where(DeclarationParticipant.declaration_id.in_([item.declaration_id for item in declarations]))
        .order_by(DeclarationParticipant.declaration_id, DeclarationParticipant.participant_ordinal)
    )


def work_queries_declaration_projections_2(_session, record_ids):
    return _session.scalars(
        select(EventDeclaration)
        .where(EventDeclaration.record_id.in_(record_ids))
        .order_by(EventDeclaration.created_at, EventDeclaration.declaration_id)
    )


def work_queries_dialogue_projections_1(_session, execution_ids):
    return _session.scalars(
        select(DialogueRecord)
        .where(DialogueRecord.creation_execution_id.in_(execution_ids))
        .order_by(DialogueRecord.creation_execution_id, DialogueRecord.start_char, DialogueRecord.candidate_key)
    )


def work_queries_character_observations_1(_session, record_by_declaration):
    return _session.scalars(
        select(DeclarationParticipant)
        .where(DeclarationParticipant.declaration_id.in_(list(record_by_declaration)))
        .order_by(DeclarationParticipant.declaration_id, DeclarationParticipant.participant_ordinal)
    )


def work_queries_character_observations_2(_session, record_ids):
    return _session.execute(
        select(EventDeclaration.declaration_id, EventDeclaration.record_id).where(
            EventDeclaration.record_id.in_(record_ids)
        )
    ).all()


def work_queries_paragraph_record(_session, run_id, paragraph_id):
    return _session.scalar(select(Paragraph).where(Paragraph.run_id == run_id, Paragraph.paragraph_id == paragraph_id))
