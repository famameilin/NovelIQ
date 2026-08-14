"""
主题建模工作流模块

本文件包含主题建模的核心业务逻辑，供多个入口复用。

主题建模为段落粒度（设计文档《章节粒度分析指标重设计》§11.1）：
paragraphs 是主题文档的唯一事实源，每个有效段落是一个 LDA 文档；
训练阶段可排除预处理后无 token 或 token_count 低于阈值的短段，
推断阶段覆盖所有预处理后有 token 的段落。
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from loguru import logger
from sqlalchemy.orm import Session

from src.api.models.events import StreamEvent
from src.config import settings
from src.storage.repositories import ParagraphRepository


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
    """
    执行主题建模流程（段落粒度，设计 §11.1）

    每个有效段落是一个 LDA 文档。训练使用预处理后仍有 token 且段落
    token_count 不低于 settings.topic_model.min_paragraph_train_tokens
    的段落；推断覆盖所有预处理后有 token 的段落（含训练排除的短段）。
    结果写入 paragraph_topics（先清后插，force 时先清空）。

    Args:
        run_id: 运行ID
        session: 数据库连接
        num_topics: 主题数量
        passes: 迭代次数
        iterations: 训练迭代次数
        top_n: 每个文档返回的 top N 主题
        force: 是否强制重新计算

    Returns:
        Tuple[int, int]: (总段落数, 主题数量)
    """
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

    # 训练文档：排除预处理后空 token 且段落 token_count < 阈值的短段（§11.1 训练可排除短段）
    min_train_tokens = settings.topic_model.min_paragraph_train_tokens
    valid_docs = [
        doc
        for doc, row in zip(tokenized_docs, paragraph_rows, strict=True)
        if doc and row.token_count >= min_train_tokens
    ]

    if not valid_docs:
        logger.warning("no valid tokens after preprocessing")
        logger.info("No valid tokens after preprocessing.")
        return 0, 0

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

    # 推断覆盖所有预处理后有 token 的段落（含训练排除的短段）
    topic_rows: list[tuple[int, int, float, int]] = []
    for row, tokens in zip(paragraph_rows, tokenized_docs, strict=True):
        if not tokens:
            continue
        results = topic_model.infer_document_topics(tokens, top_n=top_n)
        for result in results:
            topic_rows.append((row.paragraph_id, result.topic_id, result.weight, len(tokens)))

    paragraph_repo.insert_paragraph_topics(run_id, topic_rows)
    logger.info(f"inserted {len(topic_rows)} topic assignments")

    # 保存主题模型到磁盘
    model_dir = Path("models") / "topic" / run_id
    trainer.save_model(topic_model, model_dir)
    logger.info(f"saved topic model to {model_dir}")

    logger.info("\n=== Topic Summary ===")
    for topic_id in range(topic_model.num_topics):
        words = topic_model.get_topic_words(topic_id, top_n=10)
        word_str = ", ".join(f"{w.word}({w.weight:.3f})" for w in words[:5])
        logger.info(f"  Topic {topic_id + 1}: {word_str}")

    elapsed = time.time() - start_time
    logger.info(
        f"topic_model completed paragraphs={total_paragraphs} topics={topic_model.num_topics} "
        f"time={elapsed:.2f}s"
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
