"""所属领域的产物完整性查询，供恢复编排调用"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.storage.models import Paragraph, ParagraphMetric, ParagraphTopic
from src.storage.repositories import ParagraphRepository


def is_topic_model_complete(session: Session, run_id: str) -> bool:
    """LDA 构建事实、每段终态与完整 K 维分布齐备后，才能在恢复时跳过主题阶段

    inference_paragraph_count 是读取投影（complete 状态的正式聚合），
    与下面的 complete 计数同源，实际门禁仍在"每段完整 K 维分布"。
    """
    model = ParagraphRepository(session).fetch_topic_model_run(run_id)
    if model is None:
        return False
    topic_counts = (
        select(
            ParagraphTopic.paragraph_id,
            func.count().label("topic_count"),
        )
        .where(ParagraphTopic.run_id == run_id)
        .group_by(ParagraphTopic.paragraph_id)
        .subquery()
    )
    row = (
        session.execute(
            select(
                func.count(Paragraph.paragraph_id).label("total"),
                func.count(ParagraphMetric.paragraph_id)
                .filter(
                    ParagraphMetric.inference_status.in_(("complete", "empty_after_preprocess", "empty_bow")),
                )
                .label("settled"),
                func.count(ParagraphMetric.paragraph_id)
                .filter(
                    ParagraphMetric.inference_status == "complete",
                )
                .label("complete"),
                func.count(ParagraphMetric.paragraph_id)
                .filter(
                    ParagraphMetric.inference_status == "complete",
                    topic_counts.c.topic_count == model.num_topics,
                )
                .label("full_distributions"),
            )
            .select_from(Paragraph)
            .outerjoin(
                ParagraphMetric,
                (ParagraphMetric.run_id == Paragraph.run_id)
                & (ParagraphMetric.paragraph_id == Paragraph.paragraph_id),
            )
            .outerjoin(topic_counts, topic_counts.c.paragraph_id == Paragraph.paragraph_id)
            .where(Paragraph.run_id == run_id)
        )
        .mappings()
        .one()
    )
    return (
        row["total"] > 0
        and row["settled"] == row["total"]
        and row["complete"] == row["full_distributions"] == model.inference_paragraph_count
    )
