"""主题建模工作流（段落粒度）。

paragraphs 为唯一事实源；训练排除短段，推断覆盖所有有 token 段落。
结果按冻结结构落库：
- runs.lda_*：模型与实际参数、拆列后的实际 LDA 参数、语料摘要
  （模型 key/artifact 路径/推断段落数为合同投影，不落列）
- paragraph_metrics.inference_*：每个段落一行推断状态与 token 分母
- lda_paragraph_topics：完整 K 维主题分布（top_n 只属于 API 展示裁剪）

固定推断说明由固定状态合同投影，工作流只传状态。
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from loguru import logger

from src.config import settings
from src.config.paths import resolve_model_dir, resolve_project_root
from src.event_bus.notifications import StreamEvent
from src.storage import Storage
from src.topic import (
    INFERENCE_COMPLETE,
    INFERENCE_EMPTY_AFTER_PREPROCESS,
    INFERENCE_REASON_TEXTS,
    TOPIC_MODEL_KEY,
)


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
    session: Storage,
    num_topics: int | None = None,
    passes: int | None = None,
    iterations: int | None = None,
    top_n: int = 5,
    force: bool = False,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> tuple[int, int]:
    """执行主题建模，训练用达标段落，推断覆盖所有有 token 段落。

    写库顺序：LDA 实际构建列 runs.lda_* → 段落推断状态
    paragraph_metrics.inference_* → 完整分布 lda_paragraph_topics；同 run 重跑整体覆盖
    （推断列全量 upsert、主题行先删后插），不允许新旧结果混合。
    取消在段落推断的批边界生效：LDA 训练与推断是库内调用，不能中途中断
    """
    from src.utils.cancellation import check_cancelled

    _num_topics = num_topics if num_topics is not None else settings.topic_model.num_topics
    _passes = passes if passes is not None else settings.topic_model.passes
    _iterations = iterations if iterations is not None else settings.topic_model.iterations

    start_time = time.time()

    paragraph_repo = session.paragraphs

    paragraph_rows = paragraph_repo.fetch_paragraph_rows(run_id)
    if not paragraph_rows:
        logger.warning(f"no paragraphs found for run_id={run_id}")
        return 0, 0

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
    # （token_count 是 paragraph_metrics 的指标口径观测；缺失按 0 处理，不参与达标训练）
    min_train_tokens = settings.topic_model.min_paragraph_train_tokens
    filtered_empty = sum(1 for doc in tokenized_docs if not doc)
    filtered_short = sum(
        1
        for doc, row in zip(tokenized_docs, paragraph_rows, strict=True)
        if doc and int(row.token_count or 0) < min_train_tokens
    )
    valid_docs = [
        doc
        for doc, row in zip(tokenized_docs, paragraph_rows, strict=True)
        if doc and int(row.token_count or 0) >= min_train_tokens
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

    # N2：未显式指定 num_topics 时按训练文档数缩放，
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
    check_cancelled(is_cancelled)
    if emitter:
        await emitter(
            StreamEvent(
                action="progress",
                sub_stage="语料准备",
                status="completed",
                current=len(valid_docs),
                total=len(valid_docs),
                unit="段落",
            )
        )
        await emitter(StreamEvent(action="progress", sub_stage="主题训练", status="running", message="训练进度未记录"))
    import asyncio

    from src.utils.cancellation import finish_thread_step

    topic_model = await finish_thread_step(asyncio.to_thread(trainer.train, valid_docs, filter_extremes=False))
    if emitter:
        await emitter(StreamEvent(action="progress", sub_stage="主题训练", status="completed"))
    logger.info(f"LDA model trained with {topic_model.num_topics} topics")
    logger.info(f"Model trained. Inferring topics for {total_paragraphs} paragraphs...")

    # 模型 artifact 落盘后先确定 artifact_key，再写模型契约
    # （读取侧的 artifact_key 按同一 resolve_model_dir 规则投影，不再落列）
    model_dir = resolve_model_dir(run_id)
    trainer.save_model(topic_model, model_dir)
    artifact_key = str(model_dir.relative_to(resolve_project_root()).as_posix())

    # 推断覆盖全部段落：完整 K 维分布 + 每段一行推断状态
    inference_rows: list[tuple[int, int, int, str, str | None, float | None]] = []
    topic_rows: list[tuple[int, int, float]] = []
    complete_count = 0
    for processed, (row, tokens) in enumerate(zip(paragraph_rows, tokenized_docs, strict=True), start=1):
        # 推断按段落串行推进，每 64 段兑现一次取消，避免整卷推断拖住取消
        if processed % 64 == 1:
            check_cancelled(is_cancelled)
        if not tokens:
            inference_rows.append(
                (
                    row.paragraph_id,
                    row.token_count,
                    0,
                    INFERENCE_EMPTY_AFTER_PREPROCESS,
                    INFERENCE_REASON_TEXTS[INFERENCE_EMPTY_AFTER_PREPROCESS],
                    None,
                )
            )
            continue
        result = topic_model.infer_full_distribution(tokens)
        if result.inference_status != INFERENCE_COMPLETE or result.distribution is None:
            inference_rows.append(
                (
                    row.paragraph_id,
                    row.token_count,
                    result.inference_token_count,
                    result.inference_status,
                    result.unavailable_reason,
                    None,
                )
            )
            continue
        for topic_id, weight in result.distribution:
            topic_rows.append((row.paragraph_id, topic_id, weight))
        complete_count += 1
        inference_rows.append(
            (
                row.paragraph_id,
                row.token_count,
                result.inference_token_count,
                INFERENCE_COMPLETE,
                None,
                result.distribution_sum,
            )
        )

    # filter_extremes=False 与 no_below/no_above=null 是当前算法合同
    # （train(filter_extremes=False) 已在调用处固定），不再作为参数副本存储
    parameters = dict(config.to_parameters_dict())

    if emitter:
        await emitter(StreamEvent(action="progress", sub_stage="主题结果保存", status="saving"))
    paragraph_repo.save_topics(
        run_id,
        model={
            "model_key": TOPIC_MODEL_KEY,
            "library_version": _gensim_version(),
            "num_topics": topic_model.num_topics,
            "parameters": parameters,
            "dictionary_size": len(topic_model.dictionary),
            "training_document_count": len(valid_docs),
            "inference_paragraph_count": complete_count,
            "artifact_key": artifact_key,
        },
        inferences=inference_rows,
        topics=topic_rows,
    )
    if emitter:
        await emitter(
            StreamEvent(
                action="progress",
                sub_stage="主题结果保存",
                status="completed",
                current=complete_count,
                total=total_paragraphs,
                unit="段落",
            )
        )
    logger.info(f"inserted {len(topic_rows)} topic assignments for {complete_count}/{total_paragraphs} paragraphs")

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
    logger.info(f"Completed topic distributions: {complete_count}")
    logger.info(f"Topics: {topic_model.num_topics}")
    logger.info(f"Topic assignments (K*complete): {len(topic_rows)}")
    logger.info(f"Processing time: {elapsed:.2f}s")

    if emitter:
        await emitter(
            StreamEvent(action="complete", stage="topic-model", current=1, total=1, percent=100.0, sub_percent=100.0)
        )

    return total_paragraphs, topic_model.num_topics


def _gensim_version() -> str:
    """gensim 版本（契约库版本列）；导入失败时回落 unknown"""
    try:
        import gensim

        return gensim.__version__
    except ImportError:
        return "unknown"
