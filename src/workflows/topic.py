"""主题建模工作流（段落粒度 §11.1）：paragraphs 为唯一事实源，训练排除短段，推断覆盖所有有 token 段落。"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from loguru import logger
from sqlalchemy.orm import Session

from src.api.models.events import StreamEvent
from src.config import settings
from src.storage.path_resolver import resolve_model_dir
from src.storage.repositories import ParagraphRepository


def resolve_num_topics(
    num_topics: int | None,
    valid_doc_count: int,
    *,
    min_topics: int,
    max_topics: int,
    scaling_divisor: int,
) -> int:
    """N2：未显式指定 num_topics 时按训练文档数在 [min_topics, max_topics] 内缩放。

    缩放公式：valid_doc_count // scaling_divisor，缺省边界回落最小值。
    """
    if num_topics is not None:
        return num_topics
    if valid_doc_count <= 0:
        return min_topics
    return max(min_topics, min(max_topics, valid_doc_count // scaling_divisor))


async def run_topic_model(
    run_id: str,
    session: Session,
    num_topics: int | None = None,
    passes: int | None = None,
    iterations: int | None = None,
    top_n: int = 5,
    force: bool = False,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> tuple[int, int]:
    """执行主题建模（段落粒度 §11.1），训练用达标段落，推断覆盖所有有 token 段落，结果写入 paragraph_topics。"""
    _num_topics = num_topics if num_topics is not None else settings.topic_model.num_topics
    _passes = passes if passes is not None else settings.topic_model.passes
    _iterations = iterations if iterations is not None else settings.topic_model.iterations

    start_time = time.time()

    paragraph_repo = ParagraphRepository(session)

    paragraph_rows = paragraph_repo.fetch_paragraph_rows(run_id)
    if not paragraph_rows:
        logger.warning(f"no paragraphs found for run_id={run_id}")
        return 0, 0

    if force:
        paragraph_repo.clear_paragraph_topics(run_id)
        logger.info("cleared existing topic data")

    total_paragraphs = len(paragraph_rows)
    logger.info(f"loaded {total_paragraphs} paragraphs for topic modeling")
    logger.info(f"Preprocessing {total_paragraphs} paragraphs...")

    from src.topic import (
        LDAConfig,
        LDATrainer,
        TopicPreprocessor,
    )

    preprocessor = TopicPreprocessor()
    tokenized_docs = preprocessor.preprocess_documents([row.text for row in paragraph_rows])

    # 训练文档同时使用预处理结果和原始段落 token_count，分别表达可建模性与业务长度阈值
    min_train_tokens = settings.topic_model.min_paragraph_train_tokens
    filtered_empty = sum(1 for doc in tokenized_docs if not doc)
    filtered_short = sum(
        1 for doc, row in zip(tokenized_docs, paragraph_rows, strict=True) if doc and row.token_count < min_train_tokens
    )
    valid_docs = [
        doc
        for doc, row in zip(tokenized_docs, paragraph_rows, strict=True)
        if doc and row.token_count >= min_train_tokens
    ]
    logger.info(
        "训练文档筛选：总段落={}, 预处理后为空={}, 原始 token_count 低于阈值={}, 有效训练文档={}",
        total_paragraphs,
        filtered_empty,
        filtered_short,
        len(valid_docs),
    )

    if not valid_docs:
        logger.warning(
            "没有满足 Paragraph LDA 训练条件的文档：预处理后为空={}, 原始 token_count 低于阈值={}",
            filtered_empty,
            filtered_short,
        )
        return 0, 0

    # 2026-08-16 N2：未显式指定 num_topics 时按训练文档数缩放，
    # 避免 25 个主题在短书上退化为大量无行主题/权重偏斜。
    _num_topics = resolve_num_topics(
        num_topics,
        len(valid_docs),
        min_topics=settings.topic_model.num_topics_min,
        max_topics=settings.topic_model.num_topics_max,
        scaling_divisor=settings.topic_model.num_topics_scaling_divisor,
    )

    config = LDAConfig(
        num_topics=_num_topics,
        passes=_passes,
        iterations=_iterations,
    )
    trainer = LDATrainer(config)

    logger.info(f"Training LDA model with {_num_topics} topics...")
    topic_model = trainer.train(valid_docs, filter_extremes=False)
    logger.info(f"LDA model trained with {topic_model.num_topics} topics")
    logger.info(f"Model trained. Inferring topics for {total_paragraphs} paragraphs...")

    # 推断覆盖所有预处理后有 token 的段落，权重分母使用段落事实源的原始 token_count
    topic_rows: list[tuple[int, int, float, int]] = []
    for row, tokens in zip(paragraph_rows, tokenized_docs, strict=True):
        if not tokens:
            continue
        results = topic_model.infer_document_topics(tokens, top_n=top_n)
        for result in results:
            topic_rows.append((row.paragraph_id, result.topic_id, result.weight, row.token_count))

    paragraph_repo.insert_paragraph_topics(run_id, topic_rows)
    logger.info(f"inserted {len(topic_rows)} topic assignments")

    # 保存主题模型到磁盘
    model_dir = resolve_model_dir(run_id)
    trainer.save_model(topic_model, model_dir)
    logger.info(f"saved topic model to {model_dir}")

    logger.info("\n=== Topic Summary ===")
    for topic_id in range(topic_model.num_topics):
        words = topic_model.get_topic_words(topic_id, top_n=10)
        word_str = ", ".join(f"{w.word}({w.weight:.3f})" for w in words[:5])
        logger.info(f"  Topic {topic_id + 1}: {word_str}")

    elapsed = time.time() - start_time
    logger.info(
        f"topic_model completed paragraphs={total_paragraphs} topics={topic_model.num_topics} time={elapsed:.2f}s"
    )
    logger.info("\n=== Topic Model Statistics ===")
    logger.info(f"Total paragraphs: {total_paragraphs}")
    logger.info(f"Topics: {topic_model.num_topics}")
    logger.info(f"Topic assignments: {len(topic_rows)}")
    logger.info(f"Processing time: {elapsed:.2f}s")

    if emitter:
        await emitter(
            StreamEvent(action="complete", stage="topic-model", current=1, total=1, percent=100.0, sub_percent=100.0)
        )

    return total_paragraphs, topic_model.num_topics
