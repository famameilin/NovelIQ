"""text 的固定 SQL 记录查询"""

from __future__ import annotations

from sqlalchemy import func, select

from src.storage.models import (
    Chapter,
    Paragraph,
    SourceEvidence,
)


def list_chapter_paragraphs(_session, chapter_id, run_id):
    return _session.scalars(
        select(Paragraph)
        .where(Paragraph.run_id == run_id, Paragraph.chapter_id == chapter_id)
        .order_by(Paragraph.paragraph_index)
    )


def list_run_chapters(_session, run_id):
    return _session.scalars(select(Chapter).where(Chapter.run_id == run_id))


def get_chapter_sequence(_session, current_chapter_id, run_id):
    return _session.execute(
        select(Chapter.sequence).where(Chapter.run_id == run_id, Chapter.chapter_id == current_chapter_id)
    ).scalar_one_or_none()


def list_ordered_chapter_ids(_session, run_id):
    return _session.execute(
        select(Chapter.chapter_id).where(Chapter.run_id == run_id).order_by(Chapter.sequence, Chapter.chapter_id)
    ).scalars()


def get_paragraph_with_chapter_sequence(_session, paragraph_id, run_id):
    return _session.execute(
        select(Paragraph, Chapter.sequence)
        .join(Chapter, (Chapter.run_id == Paragraph.run_id) & (Chapter.chapter_id == Paragraph.chapter_id))
        .where(Paragraph.run_id == run_id, Paragraph.paragraph_id == paragraph_id)
    ).one_or_none()


def get_chapter(_session, chapter_id, run_id):
    return _session.scalar(select(Chapter).where(Chapter.run_id == run_id, Chapter.chapter_id == chapter_id))


def list_ordered_paragraphs(_session, chapter_id, run_id):
    return _session.execute(
        select(Paragraph)
        .where(Paragraph.run_id == run_id, Paragraph.chapter_id == chapter_id)
        .order_by(Paragraph.paragraph_index)
    ).scalars()


def list_passages(_session, paragraph_ids, run_id):
    return _session.scalars(
        select(Paragraph)
        .where(Paragraph.run_id == run_id, Paragraph.paragraph_id.in_(paragraph_ids))
        .order_by(Paragraph.paragraph_id)
    ).all()


def list_run_paragraphs(_session, run_id):
    return _session.scalars(select(Paragraph).where(Paragraph.run_id == run_id))


def list_readable_chapters(_session, run_id):
    return _session.scalars(
        select(Chapter)
        .where(Chapter.run_id == run_id, Chapter.text.is_not(None))
        .order_by(Chapter.sequence, Chapter.chapter_id)
    )


def get_execution_chapter(_session, execution_chapter_id, run_id):
    return _session.scalar(select(Chapter).where(Chapter.run_id == run_id, Chapter.chapter_id == execution_chapter_id))


def get_source_chapter(_session, chapter_id, run_id):
    return _session.scalar(select(Chapter).where(Chapter.run_id == run_id, Chapter.chapter_id == chapter_id))


def list_source_paragraphs(_session, chapter_id, run_id):
    return _session.scalars(
        select(Paragraph)
        .where(Paragraph.run_id == run_id, Paragraph.chapter_id == chapter_id)
        .order_by(Paragraph.paragraph_index)
    )


def list_search_hit_positions(_session, after_chapter_sequence, before_chapter_sequence, merged, run_id):
    metadata_statement = (
        select(Paragraph.paragraph_id, Paragraph.chapter_id)
        .join(Chapter, (Chapter.run_id == Paragraph.run_id) & (Chapter.chapter_id == Paragraph.chapter_id))
        .where(Paragraph.run_id == run_id, Paragraph.paragraph_id.in_(list(merged)))
    )
    if before_chapter_sequence is not None:
        metadata_statement = metadata_statement.where(Chapter.sequence < before_chapter_sequence)
    if after_chapter_sequence is not None:
        metadata_statement = metadata_statement.where(Chapter.sequence > after_chapter_sequence)
    return _session.execute(metadata_statement).all()


def count_chapters(_session, run_id):
    return _session.execute(select(func.count()).select_from(Chapter).where(Chapter.run_id == run_id)).scalar()


def get_book_end_offset(_session, run_id):
    chapter_end_char = Chapter.char_offset + func.length(Chapter.text)
    return _session.execute(select(func.max(chapter_end_char)).where(Chapter.run_id == run_id)).scalar_one_or_none()


def list_chapter_offsets(_session, run_id):
    return _session.execute(
        select(Chapter.chapter_id, Chapter.char_offset)
        .where(Chapter.run_id == run_id, Chapter.char_offset.is_not(None))
        .order_by(Chapter.sequence, Chapter.chapter_id)
    ).all()


def get_last_chapter_offset(_session, run_id):
    return _session.execute(select(func.max(Chapter.char_offset)).where(Chapter.run_id == run_id)).scalar_one_or_none()


def list_readable_run_chapters(_session, run_id):
    return _session.scalars(
        select(Chapter)
        .where(Chapter.run_id == run_id, Chapter.text.is_not(None))
        .order_by(Chapter.sequence, Chapter.chapter_id)
    ).all()


def list_owned_evidence(_session, owner_column, owner_ids, run_id):
    if owner_column not in {"graph_fact_id", "foreshadow_action_id", "complete_event_id"}:
        raise ValueError("无效的固定查询种类")
    owner_column = getattr(SourceEvidence, owner_column)
    statement = (
        select(
            owner_column.label("owner_id"),
            SourceEvidence.ordinal,
            SourceEvidence.paragraph_id,
            SourceEvidence.start_char,
            SourceEvidence.end_char,
            Paragraph.chapter_id,
            func.substr(
                Paragraph.text, SourceEvidence.start_char + 1, SourceEvidence.end_char - SourceEvidence.start_char
            ).label("quote"),
        )
        .join(Paragraph, (Paragraph.run_id == run_id) & (Paragraph.paragraph_id == SourceEvidence.paragraph_id))
        .where(owner_column.in_(owner_ids))
        .order_by(owner_column, SourceEvidence.ordinal)
    )
    return _session.execute(statement).all()


def list_owned_evidence_anchors(_session, owner_column, owner_ids, run_id):
    "只取每个所有者最早证据所在段落，供列表排序与段落级锚点使用"
    if owner_column not in {"graph_fact_id", "foreshadow_action_id", "complete_event_id"}:
        raise ValueError("无效的固定查询种类")
    owner_column = getattr(SourceEvidence, owner_column)
    statement = (
        select(
            owner_column.label("owner_id"),
            func.min(SourceEvidence.paragraph_id).label("paragraph_id"),
        )
        .join(Paragraph, (Paragraph.run_id == run_id) & (Paragraph.paragraph_id == SourceEvidence.paragraph_id))
        .where(owner_column.in_(owner_ids))
        .group_by(owner_column)
    )
    return _session.execute(statement).all()


def get_run_paragraph(_session, run_id, paragraph_id):
    return _session.scalar(select(Paragraph).where(Paragraph.run_id == run_id, Paragraph.paragraph_id == paragraph_id))


def list_ordered_run_chapters(_session, run_id):
    return (
        _session.execute(select(Chapter).where(Chapter.run_id == run_id).order_by(Chapter.sequence, Chapter.chapter_id))
        .scalars()
        .all()
    )


def list_work_paragraphs(_session, chapter, run_id):
    return (
        _session.execute(
            select(Paragraph)
            .where(Paragraph.run_id == run_id, Paragraph.chapter_id == chapter.chapter_id)
            .order_by(Paragraph.paragraph_index)
        )
        .scalars()
        .all()
    )
