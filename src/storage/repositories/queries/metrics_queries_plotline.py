"从 src/metrics/queries/plotline.py 分离的具名物理读取"

from __future__ import annotations

from sqlalchemy import func, select

from src.storage.models import Chapter, FactEntityTag, Paragraph, SourceEvidence


def metrics_queries_plotline_init_1(_session, run_id):
    return _session.scalars(
        select(Chapter)
        .where(Chapter.run_id == run_id, Chapter.text.is_not(None))
        .order_by(Chapter.sequence, Chapter.chapter_id)
    ).all()


def metrics_queries_plotline_evidence_by_owner_1(_session, owner_column, owner_ids, value_1):
    if owner_column not in {"graph_fact_id", "foreshadow_action_id", "declaration_id"}:
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
        .join(Paragraph, (Paragraph.run_id == value_1) & (Paragraph.paragraph_id == SourceEvidence.paragraph_id))
        .where(owner_column.in_(owner_ids))
        .order_by(owner_column, SourceEvidence.ordinal)
    )
    return _session.execute(statement).all()


def metrics_queries_plotline_fetch_fact_tags_1(_session, fact_ids):
    statement = (
        select(FactEntityTag.graph_fact_id, FactEntityTag.tag_ordinal, FactEntityTag.tag)
        .where(FactEntityTag.graph_fact_id.in_(fact_ids))
        .order_by(FactEntityTag.graph_fact_id, FactEntityTag.tag_ordinal)
    )
    return _session.execute(statement).all()
