"""
主题查询组装器

说明: 承载 topics 相关取数与响应装配；权重归一在
`src.metrics.aggregate.topic_aggregations.normalize_topic_weights`。

Paragraph 粒度主题结果使用 paragraph_topics 的原始 token 加权聚合
（fetch_paragraph_topics_agg），归一化使用 weighted_total
"""

from __future__ import annotations

from src.api.models.responses import TopicInfo
from src.metrics.aggregate.normalization import load_topic_words
from src.metrics.aggregate.topic_aggregations import normalize_topic_weights
from src.storage.repositories import ParagraphRepository


def _fetch_topics(run_id: str, paragraph_repo: ParagraphRepository) -> list:
    """主题权重只使用实际段落推断 token 总量归一化"""
    book_total = paragraph_repo.fetch_topic_inference_total(run_id)
    if not book_total:
        return []
    rows = paragraph_repo.fetch_paragraph_topics_agg(run_id)
    topic_words_map, topic_labels_map, _reason = load_topic_words(run_id)
    return [
        TopicInfo(**payload)
        for payload in normalize_topic_weights(
            rows,
            book_total=book_total,
            topic_words_map=topic_words_map,
            topic_labels_map=topic_labels_map,
        )
    ]
