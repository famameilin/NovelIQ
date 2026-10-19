"agents annotation chapter consolidation 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select, text

from src.storage.models import (
    Agent,
    Case,
    Chapter,
    ChapterAnnotation,
    DeclarationParticipant,
    DialogueRecord,
    EventDeclaration,
    GraphEntity,
    GraphFact,
    Paragraph,
    SourceEvidence,
)

PROGRAM_CODE = "chapter_consolidation"


def agents_annotation_chapter_consolidation_eligible_chapters_1(_session, run_id):
    return _session.execute(
        select(ChapterAnnotation.chapter_id).where(
            ChapterAnnotation.run_id == run_id
        )
    )


def agents_annotation_chapter_consolidation_consolidate_chapter_1(_session, run_id):
    return _session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"fact_graph:{run_id}"}
    )


def agents_annotation_chapter_consolidation_consolidate_chapter_2(_session, chapter_id, run_id):
    return _session.scalar(
        select(ChapterAnnotation)
        .where(
            ChapterAnnotation.run_id == run_id,
            ChapterAnnotation.chapter_id == chapter_id,
            ChapterAnnotation.consolidation_digest.is_not(None),
        )
        .limit(1)
    )


def agents_annotation_chapter_consolidation_consolidate_chapter_3(_session, run_id):
    return _session.scalars(select(ChapterAnnotation).where(ChapterAnnotation.run_id == run_id))


def agents_annotation_chapter_consolidation_consolidate_chapter_4(_session, chapter_id, run_id):
    return _session.scalars(
        select(ChapterAnnotation)
        .where(ChapterAnnotation.run_id == run_id, ChapterAnnotation.chapter_id == chapter_id)
        .order_by(ChapterAnnotation.role, ChapterAnnotation.record_id)
    )


def agents_annotation_chapter_consolidation_consolidate_chapter_5(_session, valid_executions):
    return _session.execute(
        select(GraphFact, ChapterAnnotation.chapter_id)
        .join(Agent, Agent.id == GraphFact.direct_producer_agent_id)
        .outerjoin(ChapterAnnotation, ChapterAnnotation.agent_id == Agent.id)
        .where(GraphFact.direct_producer_agent_id.in_(valid_executions))
    )


def agents_annotation_chapter_consolidation_consolidate_chapter_6(_session, fact_chapter):
    return _session.scalars(select(SourceEvidence).where(SourceEvidence.graph_fact_id.in_(list(fact_chapter))))


def agents_annotation_chapter_consolidation_consolidate_chapter_7(_session, records_by_record):
    return _session.scalars(select(EventDeclaration).where(EventDeclaration.record_id.in_(list(records_by_record))))


def agents_annotation_chapter_consolidation_consolidate_chapter_8(_session, declaration_ids):
    return _session.scalars(select(SourceEvidence).where(SourceEvidence.declaration_id.in_(declaration_ids)))


def agents_annotation_chapter_consolidation_consolidate_chapter_9(_session, declaration_ids):
    return _session.scalars(
        select(DeclarationParticipant).where(DeclarationParticipant.declaration_id.in_(declaration_ids))
    )


def agents_annotation_chapter_consolidation_consolidate_chapter_10(_session, valid_executions):
    return _session.scalars(select(DialogueRecord).where(DialogueRecord.creation_agent_id.in_(valid_executions)))


def agents_annotation_chapter_consolidation_consolidate_chapter_11(_session, chapter_id, run_id):
    return _session.scalars(
        select(Paragraph)
        .where(Paragraph.run_id == run_id, Paragraph.chapter_id == chapter_id)
        .order_by(Paragraph.paragraph_index)
    )


def agents_annotation_chapter_consolidation_consolidate_chapter_12(_session, run_id):
    return _session.scalars(select(Chapter).where(Chapter.run_id == run_id))


def agents_annotation_chapter_consolidation_consolidate_chapter_13(_session, case_ids):
    return _session.scalars(select(Case).where(Case.id.in_(case_ids)))


def agents_annotation_chapter_consolidation_consolidate_chapter_14(_session, lookup_ids):
    return _session.scalars(select(GraphEntity).where(GraphEntity.entity_id.in_(lookup_ids)))
