"""
paragraph_metrics 区块（§5.3 原始计数与充分统计量）与章节聚合

创建时间: 2026-10-02
创建者: Trae
任务: 大文件拆分——从 paragraph_repository.py 提取 paragraph_metrics
写入/读取/存在性判断与按章聚合逻辑
说明: 纯结构搬移，不改 SQL 与聚合口径；密度类比率一律在目标粒度上
重新求分子之和/分母之和，不做等权平均。
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, func, insert, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from src.storage.models import Chapter, Paragraph, ParagraphMetric
from src.storage.repositories.paragraph.rows import ParagraphMetricRow


def insert_paragraph_metrics(session: Session, run_id: str, rows: Sequence[ParagraphMetricRow]) -> int:
    """
    先删后插写入 run 的段落指标行（同 run 不可重跑前序阶段的语义）

    surface_tension 系列由计算阶段（run 内稳健标准化后）填充，可为 None
    """
    session.execute(delete(ParagraphMetric).where(ParagraphMetric.run_id == run_id))
    if not rows:
        return 0
    insert_rows = [
        {
            "run_id": run_id,
            "paragraph_id": row.paragraph_id,
            "token_count": row.token_count,
            "char_count": row.char_count,
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
            "function_word_counts": row.function_word_counts,
            "semantic_category_counts": row.semantic_category_counts,
            "surface_tension_z": row.surface_tension_z,
            "surface_tension": row.surface_tension,
        }
        for row in rows
    ]
    session.execute(insert(ParagraphMetric), insert_rows)
    return len(insert_rows)


def fetch_paragraph_metrics(session: Session, run_id: str) -> Sequence[Row]:
    """读取 run 的全部段落指标行，按 paragraph_id 升序"""
    statement = (
        select(
            ParagraphMetric.paragraph_id,
            ParagraphMetric.token_count,
            ParagraphMetric.char_count,
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
            ParagraphMetric.surface_tension_z,
            ParagraphMetric.surface_tension,
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
    按章聚合段落指标充分统计量（§9.1 分子/分母守恒）

    每行返回 (chapter_id, 字段名 → 数值) 的聚合结果，供聚合 fetchers 与
    质量门使用：密度类比率一律在目标粒度上重新求分子之和/分母之和，
    不做等权平均。
    """
    statement = (
        select(
            Paragraph.chapter_id.label("chapter_id"),
            func.sum(ParagraphMetric.token_count).label("token_count"),
            func.sum(ParagraphMetric.char_count).label("char_count"),
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
