"从 src/topic/completion.py 分离的具名物理读取"

from __future__ import annotations

from sqlalchemy import func, select

from src.storage.models import Paragraph, ParagraphMetric, ParagraphTopic


def topic_completion_is_topic_model_complete_1(_session, model, run_id):
    topic_counts = (
        select(ParagraphTopic.paragraph_id, func.count().label("topic_count"))
        .where(ParagraphTopic.run_id == run_id)
        .group_by(ParagraphTopic.paragraph_id)
        .subquery()
    )
    return (
        _session.execute(
            select(
                func.count(Paragraph.paragraph_id).label("total"),
                func.count(ParagraphMetric.paragraph_id)
                .filter(ParagraphMetric.inference_status.in_(("complete", "empty_after_preprocess", "empty_bow")))
                .label("settled"),
                func.count(ParagraphMetric.paragraph_id)
                .filter(ParagraphMetric.inference_status == "complete")
                .label("complete"),
                func.count(ParagraphMetric.paragraph_id)
                .filter(ParagraphMetric.inference_status == "complete", topic_counts.c.topic_count == model.num_topics)
                .label("full_distributions"),
            )
            .select_from(Paragraph)
            .outerjoin(
                ParagraphMetric,
                (ParagraphMetric.run_id == Paragraph.run_id) & (ParagraphMetric.paragraph_id == Paragraph.paragraph_id),
            )
            .outerjoin(topic_counts, topic_counts.c.paragraph_id == Paragraph.paragraph_id)
            .where(Paragraph.run_id == run_id)
        )
        .mappings()
        .one()
    )
