"""annotations 的固定 SQL 记录查询"""

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import (
    Agent,
    AnalysisAssessment,
    Chapter,
    ChapterAnnotation,
    DialogueRecord,
)


def list_saved_chapter_ids(_session, run_id):
    return _session.execute(select(ChapterAnnotation.chapter_id).where(ChapterAnnotation.run_id == run_id))


def find_consolidated_chapter(_session, chapter_id, run_id):
    return _session.scalar(
        select(ChapterAnnotation)
        .where(
            ChapterAnnotation.run_id == run_id,
            ChapterAnnotation.chapter_id == chapter_id,
            ChapterAnnotation.consolidation_digest.is_not(None),
        )
        .limit(1)
    )


def list_run_outputs(_session, run_id):
    return _session.scalars(select(ChapterAnnotation).where(ChapterAnnotation.run_id == run_id))


def list_chapter_role_outputs(_session, chapter_id, run_id):
    return _session.scalars(
        select(ChapterAnnotation)
        .where(ChapterAnnotation.run_id == run_id, ChapterAnnotation.chapter_id == chapter_id)
        .order_by(ChapterAnnotation.role, ChapterAnnotation.record_id)
    )


def list_dialogues_for_executions(_session, valid_executions):
    return _session.scalars(select(DialogueRecord).where(DialogueRecord.creation_agent_id.in_(valid_executions)))


def list_outputs_with_chapters(_session, run_id):
    stmt = (
        select(ChapterAnnotation, Chapter)
        .join(
            Chapter, (Chapter.run_id == ChapterAnnotation.run_id) & (Chapter.chapter_id == ChapterAnnotation.chapter_id)
        )
        .where(ChapterAnnotation.run_id == run_id)
    )
    return _session.execute(stmt).all()


def list_ordered_run_outputs(_session, run_id):
    stmt = (
        select(ChapterAnnotation)
        .where(ChapterAnnotation.run_id == run_id)
        .order_by(ChapterAnnotation.created_at, ChapterAnnotation.record_id)
    )
    return _session.scalars(stmt)


def get_output(_session, annotation_id):
    return _session.get(ChapterAnnotation, annotation_id)


def get_saved_output(_session, annotation_id):
    return _session.get(ChapterAnnotation, annotation_id)


def get_execution(_session, agent_id):
    return _session.get(Agent, agent_id)


def list_output_paragraph_labels(_session, record_ids):
    return _session.execute(
        select(AnalysisAssessment.record_id, AnalysisAssessment.paragraph_id, AnalysisAssessment.emotion)
        .where(AnalysisAssessment.record_id.in_(record_ids))
        .order_by(AnalysisAssessment.record_id, AnalysisAssessment.paragraph_id)
    )


def list_ordered_dialogues(_session, execution_ids):
    return _session.scalars(
        select(DialogueRecord)
        .where(DialogueRecord.creation_agent_id.in_(execution_ids))
        .order_by(DialogueRecord.creation_agent_id, DialogueRecord.start_char, DialogueRecord.candidate_key)
    )
