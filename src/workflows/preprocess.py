"""
预处理流程核心工作流模块

包含文本清洗、分块、写入数据库，以及风格/文化指标计算等功能。

落库结构：章节身份写 chapters、正文切片写 chapter_bodies；段落身份/原文写
paragraphs、tokenizer 计数写 paragraph_preprocess_observations；段落向量写
paragraph_embeddings，运行模型合同（模型 key + 实测维度）写 embedding_model_runs；
表面张力 z、功能词/语义类别计数写各自固定领域表。坐标、长度与密度的读取投影见各仓储模块。
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from loguru import logger

from src.config import settings
from src.sse.events import StreamEvent
from src.storage import Storage, get_storage_factory
from src.storage.records.paragraph import ParagraphMetricRow
from src.text_processing.models import ParagraphSpan
from src.text_processing.paragraphs import chunk_documents_with_chapters, split_chunk_paragraphs
from src.text_processing.preprocess import normalize_text
from src.text_processing.text_reader import ingest_path
from src.text_processing.tokenize import tokenize
from src.workflows.preprocess_readiness import is_preprocess_complete


async def run_preprocess(
    source_path: Path,
    run_id: str,
    session: Storage,
    metadata_path: Path | None = None,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> tuple[int, int, float]:
    """执行预处理流程。Args: source_path/run_id/session/metadata_path  Returns: (总块数, 总字符数, 耗时s)"""
    from src.utils.cancellation import check_cancelled
    from src.workflows.preprocess_helpers import _load_all_lexicons_for_preprocess

    start_time = time.time()
    if emitter:
        await emitter(StreamEvent(action="start", stage="preprocess", message="开始预处理", sub_percent=0.0))
    chapter_repo = session.chapters
    if is_preprocess_complete(session, run_id):
        logger.info(f"preprocess already complete for run_id={run_id}, skipping")
        return (0, 0, 0.0)
    check_cancelled(is_cancelled)
    docs = ingest_path(source_path, metadata_path)
    if not docs:
        logger.warning(f"no documents found source={source_path}")
        return (0, 0, 0.0)
    logger.info(f"loaded {len(docs)} documents from {source_path}")
    lexicons = _load_all_lexicons_for_preprocess()
    normalized_texts: list[str] = []
    for doc in docs:
        normalized = normalize_text(doc.text)
        normalized_texts.append(normalized)
    all_chunks, all_chapters = await chunk_documents_with_chapters(normalized_texts)
    total_chapters = len(all_chunks)
    total_chars = sum(len(chunk.text) for chunk in all_chunks)
    logger.info(f"chunked {total_chapters} chunks total_chars={total_chars}")
    chapter_repo = session.chapters
    chapter_repo.insert_chapters(run_id, all_chapters)
    logger.info(f"inserted {len(all_chapters)} chapters into db (run_id={run_id})")
    chapter_repo.insert_chapter_texts(run_id, all_chunks)
    logger.info(f"inserted {total_chapters} chunks into db (run_id={run_id})")
    spans = split_chunk_paragraphs(all_chunks, max_chars=settings.paragraphs.max_chars)
    tokenized: list[list[str]] = [tokenize(span.text) for span in spans]
    spans = [replace(span, token_count=len(tokens)) for span, tokens in zip(spans, tokenized, strict=True)]
    paragraph_repo = session.paragraphs
    paragraph_repo.insert_paragraphs(run_id, spans)
    logger.info(f"inserted {len(spans)} paragraphs into db (run_id={run_id})")
    if spans:
        _insert_paragraph_metrics(session, run_id, spans, tokenized, lexicons)
        _insert_paragraph_curves(session, run_id, spans)
    if settings.models.paragraph_embedding.semantic_enabled:
        logger.info("generating paragraph embeddings for semantic text retrieval")
        await _generate_paragraph_embeddings(session, run_id, emitter=emitter, is_cancelled=is_cancelled)
    elapsed = time.time() - start_time
    logger.info(f"preprocess completed chunks={total_chapters} chars={total_chars} time={elapsed:.2f}s")
    logger.info("\n=== Preprocess Statistics ===")
    logger.info(f"Total chunks: {total_chapters}")
    logger.info(f"Total characters: {total_chars}")
    logger.info(f"Processing time: {elapsed:.2f}s")
    if emitter:
        await emitter(
            StreamEvent(action="complete", stage="preprocess", current=1, total=1, percent=100.0, sub_percent=100.0)
        )
    return (total_chapters, total_chars, elapsed)


def _insert_paragraph_metrics(
    session: Storage, run_id: str, spans: list[ParagraphSpan], tokenized: list[list[str]], lexicons: dict[str, Any]
) -> list[ParagraphMetricRow]:
    """
    计算并落库段落指标（原始计数与充分统计量）

    表面张力在 run 内两遍计算：先收集全部段落的 5 个分量原始值，
    再做稳健标准化（median/MAD）得到 z，z 写入 paragraph_tension_observations
    （sigmoid 展示值不落库，由读取投影计算）。

    功能词/语义类别计数写入各自固定领域计数表，char_count 由段落正文长度投影，
    不随 paragraph_metrics 行写入。

    Returns:
        写入的 ParagraphMetricRow 列表（基础计数与充分统计量；密度/张力等派生值
        由读取投影给出）
    """
    from src.metrics.paragraph_metrics import compute_paragraph_metric_counts
    from src.metrics.paragraph_surface_tension import (
        robust_standardize_components,
        surface_tension_components,
        surface_tension_z_value,
    )

    counts_list = [
        compute_paragraph_metric_counts(span.text, tokens, lexicons)
        for span, tokens in zip(spans, tokenized, strict=True)
    ]
    z_components = robust_standardize_components([surface_tension_components(counts) for counts in counts_list])
    weights = settings.metrics.surface_tension_weights
    rows: list[ParagraphMetricRow] = []
    tension_rows: list[tuple[int, float]] = []
    function_word_rows: list[tuple[int, dict[str, int]]] = []
    semantic_category_rows: list[tuple[int, dict[str, int]]] = []
    for span, counts, z_comp in zip(spans, counts_list, z_components, strict=True):
        paragraph_id = span.paragraph_id
        if paragraph_id is None:
            raise ValueError(f"段落指标写入失败：paragraph_id 未分配，paragraph_index={span.paragraph_index}")
        rows.append(
            ParagraphMetricRow(
                paragraph_id=paragraph_id,
                token_count=counts.token_count,
                sentence_count=counts.sentence_count,
                sentence_char_sum=counts.sentence_char_sum,
                sentence_char_sum_sq=counts.sentence_char_sum_sq,
                positive_weight_sum=counts.positive_weight_sum,
                negative_weight_sum=counts.negative_weight_sum,
                fight_weight_sum=counts.fight_weight_sum,
                exclaim_count=counts.exclaim_count,
                question_count=counts.question_count,
                pause_count=counts.pause_count,
                dialogue_char_count=counts.dialogue_char_count,
                sensory_hit_count=counts.sensory_hit_count,
                imagery_hit_count=counts.imagery_hit_count,
                metaphor_sentence_count=counts.metaphor_sentence_count,
                body_reaction_hit_count=counts.body_reaction_hit_count,
            )
        )
        tension_rows.append((paragraph_id, surface_tension_z_value(z_comp, weights)))
        function_word_rows.append((paragraph_id, counts.function_word_counts))
        semantic_category_rows.append((paragraph_id, counts.semantic_category_counts))
    paragraph_repo = session.paragraphs
    paragraph_repo.save_metrics(run_id, rows, tension_rows, function_word_rows, semantic_category_rows)
    logger.info(f"inserted {len(rows)} paragraph metrics into db (run_id={run_id})")
    return rows


def _insert_paragraph_curves(session: Storage, run_id: str, spans: list[ParagraphSpan]) -> int:
    """
    计算并落库段落曲线

    段落坐标与字符权重取段落事实源读取投影（fetch_paragraph_rows：local_end/
    global 坐标/char_count 都不落列）；指标分子/分母取指标读取投影
    （fetch_paragraph_metrics：char_count 为正文长度、surface_tension 为
    sigmoid(z)、z 取自 paragraph_tension_observations），两侧从同一 run 的正式
    落库结果读取。total_chars 取段落 span 字符数之和；LOWESS 参数默认取
    settings.metrics 的 lowess_bandwidth / lowess_min_points。
    """
    from src.workflows.paragraph_curves import compute_paragraph_curves

    paragraph_repo = session.paragraphs
    paragraph_rows = paragraph_repo.fetch_paragraph_rows(run_id)
    metric_projection_rows = paragraph_repo.fetch_paragraph_metrics(run_id)
    total_chars = sum(span.char_count for span in spans)
    curve_rows = compute_paragraph_curves(
        paragraphs=paragraph_rows, metric_rows=metric_projection_rows, total_chars=total_chars
    )
    paragraph_repo.insert_paragraph_curves(run_id, curve_rows)
    logger.info(f"inserted {len(curve_rows)} paragraph curves into db (run_id={run_id})")
    return len(curve_rows)


async def _generate_paragraph_embeddings(
    session: Storage,
    run_id: str,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> int:
    """为 paragraphs 生成 embedding 落库；从 paragraphs 读不重切段，0行跳过。
    RAG 粒度固定自然段(仅 paragraph)。Args: session/run_id/emitter  Returns: embedding 数量
    """
    from src.embedding import EmbeddingClient
    from src.model_pool.usage import build_token_usage_callback
    from src.storage.records.embedding_ops import ParagraphEmbeddingRow

    paragraph_refs = session.paragraphs.fetch_paragraph_rows(run_id)
    if not paragraph_refs:
        logger.info("no paragraphs found for run_id={}, skip paragraph embeddings", run_id)
        return 0
    from src.audit.module import AuditModule
    from src.event_bus import EventBus

    pass
    audit_bus = EventBus()
    audit = AuditModule(audit_bus, run_id, get_storage_factory())
    try:
        try:
            novel_id = session.reads.workflows_preprocess_generate_paragraph_embeddings_1(run_id)
            embedding_client = EmbeddingClient(
                novel_id=novel_id if isinstance(novel_id, str) and novel_id else "unknown",
                token_usage_callback=build_token_usage_callback(bus=audit_bus, run_id=run_id),
            )
        except ValueError as e:
            raise RuntimeError(
                "embedding client initialization failed during preprocess: semantic text retr"
                "ieval requires paragraph embeddings, error="
                f"{e}"
            ) from e
        embedding_dim = await embedding_client.detect_embedding_dimension()
        session.prepare_paragraph_vectors(embedding_dim)
        paragraph_rows = await _generate_paragraph_embedding_rows(
            embedding_client, run_id, ParagraphEmbeddingRow, emitter=emitter, is_cancelled=is_cancelled
        )
        if paragraph_rows:
            session.paragraphs.insert_paragraph_embeddings(run_id, paragraph_rows, embedding_dimension=embedding_dim)
            logger.info("inserted {} paragraph embeddings into db (run_id={})", len(paragraph_rows), run_id)
        if emitter:
            await emitter(
                StreamEvent(action="complete", stage="preprocess", message="向量嵌入生成完成", sub_percent=100.0)
            )
        return len(paragraph_rows)
    finally:
        await audit.close()


async def _generate_paragraph_embedding_rows(
    embedding_client: Any,
    run_id: str,
    row_factory: Any,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> list[Any]:
    """生成 paragraph embedding 写入 DTO — 段落源 paragraphs(不重切，仅 paragraph_id+向量)，
    坐标从 paragraphs 读；批量 embed_texts 防单条退化。缺失 fail fast(防 readiness 假成功)，progress_callback 发 SSE。
    """
    pass
    pass
    from src.utils.cancellation import check_cancelled

    session = get_storage_factory()()
    paragraph_refs: list[tuple[int, int, int, int, int, int, int, str]] = []
    for row in session.paragraphs.fetch_paragraph_rows(run_id):
        paragraph_refs.append(
            (
                row.paragraph_id,
                row.chapter_id,
                row.paragraph_index,
                row.local_start_char,
                row.local_end_char,
                row.global_start_char,
                row.global_end_char,
                row.text,
            )
        )
    if not paragraph_refs:
        return []

    async def _emit_paragraph_embedding_progress(completed_batches: int, total_batches: int, total_items: int) -> None:
        """
        发射 preprocess 阶段 paragraph embedding 的批次进度

        """
        check_cancelled(is_cancelled)
        if emitter is None or total_batches <= 0:
            return
        sub_percent = completed_batches / total_batches * 100
        await emitter(
            StreamEvent(
                action="progress",
                stage="preprocess",
                sub_stage="paragraph_embedding",
                current=completed_batches,
                total=total_batches,
                sub_percent=sub_percent,
                message=f"段落向量落库准备 {completed_batches}/{total_batches} 批（共 {total_items} 段）",
            )
        )

    paragraph_texts = [paragraph_text for _, _, _, _, _, _, _, paragraph_text in paragraph_refs]
    paragraph_embeddings = await embedding_client.embed_texts(
        paragraph_texts, progress_callback=_emit_paragraph_embedding_progress
    )
    if len(paragraph_embeddings) != len(paragraph_refs):
        raise RuntimeError(
            "paragraph embedding result count mismatch: expected "
            f"{len(paragraph_refs)}"
            ", got "
            f"{len(paragraph_embeddings)}"
        )
    rows = []
    missing_refs: list[tuple[int, int]] = []
    for (
        paragraph_id,
        chapter_id,
        paragraph_index,
        _local_start_char,
        _local_end_char,
        _global_start_char,
        _global_end_char,
        _paragraph_text,
    ), embedding in zip(paragraph_refs, paragraph_embeddings, strict=True):
        if not embedding:
            logger.error(
                "empty paragraph embedding detected: run_id={} chapter_id={} paragraph_index={}",
                run_id,
                chapter_id,
                paragraph_index,
            )
            missing_refs.append((chapter_id, paragraph_index))
            continue
        rows.append(row_factory(paragraph_id=paragraph_id, embedding_vector=embedding))
    if missing_refs:
        preview_refs = ", ".join(
            (f"{chapter_id}:{paragraph_index}" for chapter_id, paragraph_index in missing_refs[:10])
        )
        raise RuntimeError(
            "paragraph embeddings incomplete during preprocess: run_id="
            f"{run_id}"
            ", missing="
            f"{preview_refs}"
            ", total="
            f"{len(missing_refs)}"
        )
    return rows
