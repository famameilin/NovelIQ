"""主题 tab 组装（主题总览）"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from src.api.services.results_queries.diagnosis import _fetch_diagnosis
from src.api.services.results_queries.keywords import compute_keywords
from src.api.services.results_queries.topic_aggregations import (
    aggregate_book_topics,
    aggregate_chapter_topics,
)
from src.api.services.results_queries.topics import _fetch_topics
from src.storage.repositories import ParagraphRepository, StatsRepository


def build_topics_overview(run_id: str, session: Session, novel_id: str) -> dict[str, Any]:
    """
    主题总览 tab：主题词 + 全书/章节完整分布 + TextRank 关键词 + 诊断主题标签

    - 主题词沿用 /topics 的模型工件读取口径（无工件时 words 为空）
    - 分布与 unavailable_reason 以全书聚合为准（章节级同一模型契约）
    - TextRank 关键词与 LDA 口径独立，单独回显不可用原因
    - topic_labels 取自诊断切片（LLM 主题命名，原前端融合逻辑并入服务端）
    """
    paragraph_repo = ParagraphRepository(session)
    topics = _fetch_topics(run_id, paragraph_repo)
    book = aggregate_book_topics(run_id, session)
    chapters = aggregate_chapter_topics(run_id, session)
    keywords = compute_keywords(run_id, session, top_n=10)
    diagnosis = _fetch_diagnosis(run_id, novel_id, StatsRepository(session))

    return {
        "run_id": run_id,
        "model": book.get("model"),
        "topics": topics,
        "distribution": book.get("distribution"),
        "chapters": chapters.get("chapters", []),
        "keywords": keywords.get("keywords", []),
        "topic_labels": diagnosis.topic_labels if diagnosis is not None else None,
        "unavailable_reason": book.get("unavailable_reason"),
        "keyword_unavailable_reason": keywords.get("unavailable_reason"),
    }
