"""
主题建模工作流模块

创建时间: 2026-03-14
创建者: TraeAI
任务: 从 cli/topic.py 提取核心业务逻辑到 workflows 模块
说明: 本文件包含主题建模的核心业务逻辑，从 src/cli/topic.py 提取而来，
      供 CLI 和其他模块复用。

修改时间: 2026-03-14
修改者: TraeAI
任务: workflows 使用 Repository 模式重构
修改内容: 添加 run_id/session 参数支持，使用 ChunkRepository 替代直接调用 operations 函数

修改时间: 2026-04-09
修改者: TraeAI
任务: 重构其他 workflow 为 async
修改内容: run_topic_model 改为 async def，所有内部调用改为 await
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from loguru import logger
from sqlalchemy.orm import Session

from src.api.models.events import StreamEvent
from src.config import settings
from src.storage.repositories import ChunkRepository


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
    执行主题建模流程

    创建时间: 2025-03-11
    创建者: TraeAI
    任务: 主题建模流程

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: workflows 使用 Repository 模式重构
    修改内容: 添加 run_id/session 参数，支持 Repository 模式

    修改时间: 2026-04-25
    修改者: Codex
    任务: remove-unused-workflow-cache-hooks
    修改内容: 删除未被主链实际消费的 cache_path 参数，避免保留无效缓存接口。

    Args:
        run_id: 运行ID
        session: 数据库连接
        num_topics: 主题数量
        passes: 迭代次数
        iterations: 训练迭代次数
        top_n: 每个文档返回的 top N 主题
        force: 是否强制重新计算

    Returns:
        Tuple[int, int]: (总块数, 主题数量)
    """
    _num_topics = num_topics if num_topics is not None else settings.topic_model.single_book.num_topics
    _passes = passes if passes is not None else settings.topic_model.single_book.passes
    _iterations = iterations if iterations is not None else settings.topic_model.single_book.iterations

    start_time = time.time()

    chunk_repo = ChunkRepository(session)

    chunk_texts = chunk_repo.fetch_chunk_texts(run_id)
    if not chunk_texts:
        logger.warning(f"no chunks found for run_id={run_id}")
        return 0, 0

    if force:
        chunk_repo.clear_chunk_topics(run_id)
        logger.info("cleared existing topic data")

    total_chunks = len(chunk_texts)
    logger.info(f"loaded {total_chunks} chunks for topic modeling")
    logger.info(f"Preprocessing {total_chunks} chunks...")

    from src.topic import (
        LDAConfig,
        LDATrainer,
        TopicPreprocessor,
    )

    preprocessor = TopicPreprocessor()
    tokenized_docs = preprocessor.preprocess_documents([text for _, text in chunk_texts])
    valid_docs = [doc for doc in tokenized_docs if doc]

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
    logger.info(f"Model trained. Inferring topics for {total_chunks} chunks...")

    topic_rows: list[tuple[int, int, float]] = []
    for idx, tokens in enumerate(tokenized_docs):
        if not tokens:
            continue
        results = topic_model.infer_document_topics(tokens, top_n=top_n)
        for result in results:
            topic_rows.append((chunk_texts[idx][0], result.topic_id, result.weight))

    chunk_repo.insert_chunk_topics(run_id, topic_rows)
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
    logger.info(f"topic_model completed chunks={total_chunks} topics={topic_model.num_topics} time={elapsed:.2f}s")
    logger.info("\n=== Topic Model Statistics ===")
    logger.info(f"Total chunks: {total_chunks}")
    logger.info(f"Topics: {topic_model.num_topics}")
    logger.info(f"Topic assignments: {len(topic_rows)}")
    logger.info(f"Processing time: {elapsed:.2f}s")

    if emitter:
        await emitter(
            StreamEvent(action="complete", stage="topic-model", current=1, total=1, percent=100.0, sub_percent=100.0)
        )

    return total_chunks, topic_model.num_topics
