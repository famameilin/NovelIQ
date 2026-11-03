"""语言统计与情绪词元观测的数据库聚合"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, or_, select, tuple_
from sqlalchemy.orm import aliased

from src.storage.models import LinguisticSpan, Paragraph, ParagraphFeature, ParagraphMetric
from src.storage.records.linguistic import (
    LINGUISTIC_COUNT_FIELDS,
    LINGUISTIC_GROUP_PREFIXES,
    LINGUISTIC_REQUIRED_CODES,
    LINGUISTIC_SCALAR_FIELDS,
    SENTENCE_CODE_TO_KEY,
)


def get_statistics_completion_counts(session, run_id: str) -> dict[str, int]:
    """统计段落数、语言完成数及必需统计齐全的段落数"""
    coverage = (
        select(ParagraphFeature.paragraph_id, func.count().label("code_count"))
        .where(ParagraphFeature.run_id == run_id, ParagraphFeature.feature_code.in_(LINGUISTIC_REQUIRED_CODES))
        .group_by(ParagraphFeature.paragraph_id)
        .subquery()
    )
    row = session.execute(
        select(
            func.count(Paragraph.paragraph_id).label("total"),
            func.count(ParagraphMetric.paragraph_id)
            .filter(ParagraphMetric.linguistic_completed_at.is_not(None)).label("completed"),
            func.count(coverage.c.paragraph_id).filter(
                ParagraphMetric.linguistic_completed_at.is_not(None),
                ParagraphMetric.sentence_count.is_not(None),
                coverage.c.code_count == len(LINGUISTIC_REQUIRED_CODES),
            ).label("statistics_completed"),
        )
        .select_from(Paragraph)
        .outerjoin(ParagraphMetric, and_(
            ParagraphMetric.run_id == Paragraph.run_id, ParagraphMetric.paragraph_id == Paragraph.paragraph_id,
        ))
        .outerjoin(coverage, coverage.c.paragraph_id == Paragraph.paragraph_id)
        .where(Paragraph.run_id == run_id)
    ).one()
    return {key: int(value) for key, value in row._mapping.items()}


def _groups(column):
    return func.grouping_sets(tuple_(column), tuple_())


def fetch_statistics_aggregates(session, run_id: str) -> dict[str, Any]:
    """完整统计按书和章节聚合，不重新解析词元或依存弧"""
    coverage = get_statistics_completion_counts(session, run_id)
    payload: dict[str, Any] = {**coverage, "groups": [], "holders": [], "predicates": []}
    if not coverage["completed"] or coverage["statistics_completed"] != coverage["total"]:
        raise ValueError("正式语言统计不符合完整性契约")
    completed = (
        select(
            Paragraph.paragraph_id, Paragraph.chapter_id, Paragraph.text,
            ParagraphMetric.sentence_count, ParagraphMetric.boundary_pos_score_sum,
            ParagraphMetric.boundary_neg_score_sum,
        )
        .join(ParagraphMetric, and_(
            ParagraphMetric.run_id == Paragraph.run_id, ParagraphMetric.paragraph_id == Paragraph.paragraph_id,
        ))
        .where(Paragraph.run_id == run_id, ParagraphMetric.linguistic_completed_at.is_not(None))
        .cte("linguistic_completed")
    )
    groups: dict[int | None, dict[str, Any]] = {}
    for row in session.execute(
        select(
            completed.c.chapter_id, func.sum(completed.c.sentence_count).label("sentence_total"),
            func.sum(completed.c.boundary_pos_score_sum).label("boundary_pos_score_sum"),
            func.sum(completed.c.boundary_neg_score_sum).label("boundary_neg_score_sum"),
        ).group_by(_groups(completed.c.chapter_id))
    ):
        groups[row.chapter_id] = {
            "chapter_id": row.chapter_id, "sentence_total": int(row.sentence_total),
            "boundary_pos_score_sum": row.boundary_pos_score_sum,
            "boundary_neg_score_sum": row.boundary_neg_score_sum,
            **dict.fromkeys(LINGUISTIC_COUNT_FIELDS, 0),
            **dict.fromkeys(LINGUISTIC_SCALAR_FIELDS, 0.0),
            **{field: {} for field in (*LINGUISTIC_GROUP_PREFIXES, "sentence_pattern_counts")},
            "emotion_event_count": 0, "emotion_pos_event_count": 0,
            "emotion_neg_event_count": 0, "emotion_negated_event_count": 0,
        }
    codes = ParagraphFeature.feature_code
    selected_codes = or_(
        codes.in_((*LINGUISTIC_COUNT_FIELDS, *LINGUISTIC_SCALAR_FIELDS, *SENTENCE_CODE_TO_KEY)),
        *(codes.startswith(prefix, autoescape=True) for prefix in LINGUISTIC_GROUP_PREFIXES.values()),
    )
    for row in session.execute(
        select(
            completed.c.chapter_id, codes,
            func.sum(ParagraphFeature.count_value).label("count_value"),
            func.max(ParagraphFeature.count_value).label("maximum"),
            func.sum(ParagraphFeature.scalar_value).label("scalar_value"),
        )
        .select_from(ParagraphFeature)
        .join(completed, completed.c.paragraph_id == ParagraphFeature.paragraph_id)
        .where(ParagraphFeature.run_id == run_id, selected_codes)
        .group_by(func.grouping_sets(tuple_(completed.c.chapter_id, codes), tuple_(codes)))
    ):
        group = groups[row.chapter_id]
        code = row.feature_code
        if code in LINGUISTIC_COUNT_FIELDS:
            group[code] = int(row.maximum if code == "dependency_depth_max" else row.count_value)
        elif code in LINGUISTIC_SCALAR_FIELDS:
            group[code] = float(row.scalar_value)
        elif code in SENTENCE_CODE_TO_KEY:
            group["sentence_pattern_counts"][SENTENCE_CODE_TO_KEY[code]] = int(row.count_value)
        else:
            for field, prefix in LINGUISTIC_GROUP_PREFIXES.items():
                if code.startswith(prefix):
                    group[field][code.removeprefix(prefix)] = int(row.count_value)
                    break

    for row in session.execute(
        select(
            completed.c.chapter_id, func.count().label("total"),
            func.count().filter(LinguisticSpan.emotion_polarity == "positive").label("positive"),
            func.count().filter(LinguisticSpan.emotion_polarity == "negative").label("negative"),
            func.count().filter(LinguisticSpan.emotion_negated.is_(True)).label("negated"),
        )
        .select_from(LinguisticSpan)
        .join(completed, completed.c.paragraph_id == LinguisticSpan.paragraph_id)
        .where(LinguisticSpan.run_id == run_id, LinguisticSpan.emotion_polarity.is_not(None))
        .group_by(_groups(completed.c.chapter_id))
    ):
        groups[row.chapter_id].update(
            emotion_event_count=int(row.total), emotion_pos_event_count=int(row.positive),
            emotion_neg_event_count=int(row.negative), emotion_negated_event_count=int(row.negated),
        )

    holder = aliased(LinguisticSpan)
    events = (
        select(
            LinguisticSpan.paragraph_id, LinguisticSpan.token_index,
            func.substr(completed.c.text, LinguisticSpan.start_char + 1,
                        LinguisticSpan.end_char - LinguisticSpan.start_char).label("predicate"),
            LinguisticSpan.emotion_polarity.label("polarity"),
            func.substr(completed.c.text, holder.start_char + 1, holder.end_char - holder.start_char).label("holder"),
        )
        .join(completed, completed.c.paragraph_id == LinguisticSpan.paragraph_id)
        .outerjoin(holder, and_(
            holder.run_id == LinguisticSpan.run_id, holder.paragraph_id == LinguisticSpan.paragraph_id,
            holder.token_index == LinguisticSpan.emotion_holder_token_index,
        ))
        .where(LinguisticSpan.run_id == run_id, LinguisticSpan.emotion_polarity.is_not(None))
        .cte("linguistic_emotion_events")
    )
    holder_counts = (
        select(
            events.c.holder, func.count().label("event_count"),
            func.count().filter(events.c.polarity == "positive").label("positive_count"),
            func.count().filter(events.c.polarity == "negative").label("negative_count"),
        ).where(events.c.holder.is_not(None), events.c.holder != "")
        .group_by(events.c.holder).subquery()
    )
    first_holder = (
        select(events.c.holder, events.c.paragraph_id, events.c.token_index)
        .distinct(events.c.holder).order_by(events.c.holder, events.c.paragraph_id, events.c.token_index)
        .subquery()
    )
    payload["holders"] = session.execute(
        select(holder_counts).join(first_holder, holder_counts.c.holder == first_holder.c.holder)
        .order_by(holder_counts.c.event_count.desc(), first_holder.c.paragraph_id, first_holder.c.token_index).limit(20)
    ).mappings().all()
    predicate_counts = (
        select(events.c.predicate, events.c.polarity, func.count().label("event_count"))
        .group_by(events.c.predicate, events.c.polarity).subquery()
    )
    first_predicate = (
        select(events.c.predicate, events.c.polarity, events.c.paragraph_id, events.c.token_index)
        .distinct(events.c.predicate, events.c.polarity)
        .order_by(events.c.predicate, events.c.polarity, events.c.paragraph_id, events.c.token_index).subquery()
    )
    payload["predicates"] = session.execute(
        select(predicate_counts).join(first_predicate, and_(
            predicate_counts.c.predicate == first_predicate.c.predicate,
            predicate_counts.c.polarity == first_predicate.c.polarity,
        ))
        .order_by(predicate_counts.c.event_count.desc(), first_predicate.c.paragraph_id, first_predicate.c.token_index)
        .limit(20)
    ).mappings().all()
    payload["groups"] = list(groups.values())
    return payload
