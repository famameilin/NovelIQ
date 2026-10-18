"""
paragraph_metrics 区块（原始计数与充分统计量）与章节聚合

密度类比率一律在目标粒度上重新求分子之和/分母之和，不做等权平均。

- char_count 由段落正文长度读投影；功能词/语义类别计数写本表的
  20 个 fw_* / 10 个 semantic_* 列；表面张力 z 写 paragraph_features 的
  tension_z 行，sigmoid 后的 surface_tension 由读取投影给出（NULL→NULL）
- 读取用 SQL 投影补齐下游既有形状，不改变计算口径
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, func, insert, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from src.storage.models import Chapter, Paragraph, ParagraphFeature, ParagraphMetric
from src.storage.repositories.metric_inputs import (
    FEATURE_TENSION_Z,
    char_count_projection,
    surface_tension_projection,
)
from src.storage.repositories.paragraph.rows import ParagraphMetricRow


def insert_paragraph_metrics(session: Session, run_id: str, rows: Sequence[ParagraphMetricRow]) -> int:
    """
    先删后插写入 run 的段落指标行

    只写基础计数与充分统计量列；char_count、分类计数与表面张力 z 不写本表，
    由读取投影或 fw_*/semantic_* 明确列、paragraph_features 的 tension_z 行承接。
    """
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
    """读取 run 的全部段落指标行，按 paragraph_id 升序

    char_count 与 surface_tension 为读投影（正文长度 / sigmoid(z)）；
    surface_tension_z 取自 paragraph_features 的 tension_z 行，无观测为 NULL。
    """
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
    """run 是否存在段落指标行"""
    statement = select(ParagraphMetric.paragraph_id).where(ParagraphMetric.run_id == run_id).limit(1)
    return session.execute(statement).scalar_one_or_none() is not None


def fetch_chapter_metric_aggregates(session: Session, run_id: str) -> list[tuple[int, dict[str, float]]]:
    """
    按章聚合段落指标充分统计量（分子/分母守恒）

    每行返回 (chapter_id, 字段名 → 数值) 的聚合结果，供聚合 fetchers 与
    质量门使用：密度类比率一律在目标粒度上重新求分子之和/分母之和，
    不做等权平均。char_count 由段落正文长度投影后求和。
    """
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
