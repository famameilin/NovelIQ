"""所属领域的产物完整性查询，供恢复编排调用"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.storage.models import (
    Paragraph,
    ParagraphTopic,
    ParagraphTopicInference,
    TopicModelRun,
)


def is_topic_model_complete(session: Session, run_id: str) -> bool:
    """模型契约、每段终态与完整 K 维分布齐备后，才能在恢复时跳过主题阶段"""
    model = session.get(TopicModelRun, run_id)
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
                func.count(ParagraphTopicInference.paragraph_id)
                .filter(
                    ParagraphTopicInference.inference_status.in_(("complete", "empty_after_preprocess", "empty_bow")),
                )
                .label("settled"),
                func.count(ParagraphTopicInference.paragraph_id)
                .filter(
                    ParagraphTopicInference.inference_status == "complete",
                )
                .label("complete"),
                func.count(ParagraphTopicInference.paragraph_id)
                .filter(
                    ParagraphTopicInference.inference_status == "complete",
                    topic_counts.c.topic_count == model.num_topics,
                )
                .label("full_distributions"),
            )
            .select_from(Paragraph)
            .outerjoin(
                ParagraphTopicInference,
                (ParagraphTopicInference.run_id == Paragraph.run_id)
                & (ParagraphTopicInference.paragraph_id == Paragraph.paragraph_id),
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
