"paragraph_metrics 区块（ 原始计数与充分统计量）与章节聚合"

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, func, insert, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from src.storage.models import Chapter, Paragraph, ParagraphFeature, ParagraphMetric
from src.storage.records.paragraph import ParagraphMetricRow
from src.storage.repositories.metric_inputs import (
    FEATURE_TENSION_Z,
    char_count_projection,
    surface_tension_projection,
)


def insert_paragraph_metrics(session: Session, run_id: str, rows: Sequence[ParagraphMetricRow]) -> int:
    "先删后插写入 run 的段落指标行（同 run 不可重跑前序阶段的语义）"
    session.execute(delete(ParagraphMetric).where(ParagraphMetric.run_id == run_id))
    if not rows:
        return 0
    insert_rows = [
        {
            "run_id": run_id,
            "paragraph_id": row.paragraph_id,
            "token_count": row.token_count,
            "sentence_count": row.sentence_count,
            "sentence_char_sum": row.sentence_char_sum,
            "sentence_char_sum_sq": row.sentence_char_sum_sq,
            "positive_weight_sum": row.positive_weight_sum,
            "negative_weight_sum": row.negative_weight_sum,
            "fight_weight_sum": row.fight_weight_sum,
            "exclaim_count": row.exclaim_count,
            "question_count": row.question_count,
            "pause_count": row.pause_count,
            "dialogue_char_count": row.dialogue_char_count,
            "sensory_hit_count": row.sensory_hit_count,
            "imagery_hit_count": row.imagery_hit_count,
            "metaphor_sentence_count": row.metaphor_sentence_count,
            "body_reaction_hit_count": row.body_reaction_hit_count,
        }
        for row in rows
    ]
    session.execute(insert(ParagraphMetric), insert_rows)
    return len(insert_rows)


def fetch_paragraph_metrics(session: Session, run_id: str) -> Sequence[Row]:
    "读取 run 的全部段落指标行，按 paragraph_id 升序"
    statement = (
        select(
            ParagraphMetric.paragraph_id,
            ParagraphMetric.token_count,
            char_count_projection().label("char_count"),
            ParagraphMetric.sentence_count,
            ParagraphMetric.sentence_char_sum,
            ParagraphMetric.sentence_char_sum_sq,
            ParagraphMetric.positive_weight_sum,
            ParagraphMetric.negative_weight_sum,
            ParagraphMetric.fight_weight_sum,
            ParagraphMetric.exclaim_count,
            ParagraphMetric.question_count,
            ParagraphMetric.pause_count,
            ParagraphMetric.dialogue_char_count,
            ParagraphMetric.sensory_hit_count,
            ParagraphMetric.imagery_hit_count,
            ParagraphMetric.metaphor_sentence_count,
            ParagraphMetric.body_reaction_hit_count,
            ParagraphFeature.scalar_value.label("surface_tension_z"),
            surface_tension_projection().label("surface_tension"),
        )
        .join(
            Paragraph,
            (Paragraph.run_id == ParagraphMetric.run_id) & (Paragraph.paragraph_id == ParagraphMetric.paragraph_id),
        )
        .join(
            ParagraphFeature,
            (ParagraphFeature.run_id == ParagraphMetric.run_id)
            & (ParagraphFeature.paragraph_id == ParagraphMetric.paragraph_id)
            & (ParagraphFeature.feature_code == FEATURE_TENSION_Z),
            isouter=True,
        )
        .where(ParagraphMetric.run_id == run_id)
        .order_by(ParagraphMetric.paragraph_id)
    )
    return session.execute(statement).all()


def has_paragraph_metrics(session: Session, run_id: str) -> bool:
    "run 是否存在段落指标行"
    statement = select(ParagraphMetric.paragraph_id).where(ParagraphMetric.run_id == run_id).limit(1)
    return session.execute(statement).scalar_one_or_none() is not None


def fetch_chapter_metric_aggregates(session: Session, run_id: str) -> list[tuple[int, dict[str, float]]]:
    "按章聚合段落指标充分统计量（ 分子/分母守恒）"
    statement = (
        select(
            Paragraph.chapter_id.label("chapter_id"),
            func.sum(ParagraphMetric.token_count).label("token_count"),
            func.sum(char_count_projection()).label("char_count"),
            func.sum(ParagraphMetric.sentence_count).label("sentence_count"),
            func.sum(ParagraphMetric.sentence_char_sum).label("sentence_char_sum"),
            func.sum(ParagraphMetric.positive_weight_sum).label("positive_weight_sum"),
            func.sum(ParagraphMetric.negative_weight_sum).label("negative_weight_sum"),
            func.sum(ParagraphMetric.dialogue_char_count).label("dialogue_char_count"),
            func.sum(ParagraphMetric.imagery_hit_count).label("imagery_hit_count"),
        )
        .join(
            Paragraph,
            (Paragraph.run_id == ParagraphMetric.run_id) & (Paragraph.paragraph_id == ParagraphMetric.paragraph_id),
        )
        .join(
            Chapter,
            (Chapter.run_id == Paragraph.run_id) & (Chapter.chapter_id == Paragraph.chapter_id),
        )
        .where(ParagraphMetric.run_id == run_id)
        .group_by(Paragraph.chapter_id, Chapter.sequence)
        .order_by(Chapter.sequence, Paragraph.chapter_id)
    )
    rows = session.execute(statement).all()
    return [(int(row.chapter_id), {key: float(value) for key, value in row._mapping.items()}) for row in rows]
