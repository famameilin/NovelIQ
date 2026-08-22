"""
预处理流程核心工作流模块

包含文本清洗、分块、写入数据库，以及风格/文化指标计算等功能。


"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.models.events import StreamEvent
from src.chunking.chunker import chunk_documents_with_chapters, split_chunk_paragraphs
from src.chunking.spans import ParagraphSpan
from src.config import settings
from src.ingest.reader import ingest_path
from src.preprocess.cleaning import normalize_text
from src.preprocess.tokenize import tokenize
from src.storage.repositories import (
    ChapterRepository,
)
from src.storage.repositories.paragraph_repository import (
    ParagraphMetricRow,
    ParagraphRepository,
)
from src.storage.vector_schema import (
    ensure_paragraph_embeddings_schema,
)


async def run_preprocess(
    source_path: Path,
    run_id: str,
    session: Session,
    metadata_path: Path | None = None,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> tuple[int, int, float]:
    """执行预处理流程。Args: source_path/run_id/session/metadata_path  Returns: (总块数, 总字符数, 耗时s)"""
    from src.workflows.preprocess_helpers import _load_all_lexicons_for_preprocess

    start_time = time.time()

    if emitter:
        await emitter(StreamEvent(action="start", stage="preprocess", message="开始预处理", sub_percent=0.0))

    chapter_repo = ChapterRepository(session)
    if chapter_repo.is_preprocess_complete(run_id):
        logger.info(f"preprocess already complete for run_id={run_id}, skipping")
        return 0, 0, 0.0

    docs = ingest_path(source_path, metadata_path)
    if not docs:
        logger.warning(f"no documents found source={source_path}")
        return 0, 0, 0.0
    logger.info(f"loaded {len(docs)} documents from {source_path}")

    lexicons = _load_all_lexicons_for_preprocess()

    normalized_texts: list[str] = []
    for doc in docs:
        normalized = normalize_text(doc.text)
        normalized_texts.append(normalized)

    all_chunks, all_chapters = await chunk_documents_with_chapters(
        normalized_texts,
        emitter=emitter,
    )

    total_chapters = len(all_chunks)
    total_chars = sum(len(chunk.text) for chunk in all_chunks)
    logger.info(f"chunked {total_chapters} chunks total_chars={total_chars}")

    chapter_repo = ChapterRepository(session)
    chapter_repo.insert_chapters(run_id, all_chapters)
    _commit_preprocess_writes(session, step="insert_chapters")
    logger.info(f"inserted {len(all_chapters)} chapters into db (run_id={run_id})")

    chapter_repo.insert_chapter_texts(run_id, all_chunks)
    _commit_preprocess_writes(session, step="insert_chapter_texts")
    logger.info(f"inserted {total_chapters} chunks into db (run_id={run_id})")

    # 段落事实源：chunks 落库后无条件生成段落行（语义检索开关不影响 paragraphs 的生成和内容），
    # 段落身份以 paragraphs 表为准，embedding/检索/指标均从该表读取，保证与段落严格对齐
    spans = split_chunk_paragraphs(all_chunks, max_chars=settings.paragraphs.max_chars)
    tokenized: list[list[str]] = [tokenize(span.text) for span in spans]
    spans = [replace(span, token_count=len(tokens)) for span, tokens in zip(spans, tokenized, strict=True)]
    paragraph_repo = ParagraphRepository(session)
    paragraph_repo.insert_paragraphs(run_id, spans)
    _commit_preprocess_writes(session, step="insert_paragraphs")
    logger.info(f"inserted {len(spans)} paragraphs into db (run_id={run_id})")

    # 段落指标（§5.3）：原始计数与充分统计量；surface_tension 在 run 内稳健标准化后写入
    if spans:
        metric_rows = _insert_paragraph_metrics(session, run_id, spans, tokenized, lexicons)
        _insert_paragraph_curves(session, run_id, spans, metric_rows)

    # 2026-08-14 M8b：chunk_style 链已删除——风格指标以 paragraph_metrics
    # 的充分统计量（sentence_count/sum/sum_sq、dialogue_char_count 等）为事实源。
    if settings.models.paragraph_embedding.semantic_enabled:
        logger.info("generating paragraph embeddings for semantic text retrieval")
        await _generate_paragraph_embeddings(session, run_id, emitter=emitter)

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

    return total_chapters, total_chars, elapsed


def _commit_preprocess_writes(session: Session, *, step: str) -> None:
    """
    提交 preprocess 阶段的分段写入，及时释放事务锁

    preprocess 会连续写 chapters、paragraphs、paragraph_metrics/paragraph_curves 与 paragraph_embeddings，
          这些表都外键关联 analysis_runs
          若整段预处理共用一个长事务，EventBus 另一条连接更新 analysis_runs 时可能被阻塞到 statement timeout
          因此这里在关键批量写入后立即提交，主动切断长事务
    """
    # 这里的 commit 目标是缩短锁持有时间，而不是改变业务原子性边界；
    # preprocess 本身已是可恢复阶段，分段提交比让状态写回超时更符合当前系统语义
    session.commit()
    logger.debug(f"Committed preprocess writes after step={step}")


def _insert_paragraph_metrics(
    session: Session,
    run_id: str,
    spans: list[ParagraphSpan],
    tokenized: list[list[str]],
    lexicons: dict[str, Any],
) -> list[ParagraphMetricRow]:
    """
    计算并落库段落指标（§5.3 原始计数与充分统计量）

    表面张力（§9.2）在 run 内两遍计算：先收集全部段落的 5 个分量原始值，
    再做稳健标准化（median/MAD）得到 z，sigmoid 后与 z 一并写入
    paragraph_metrics 行。

    Returns:
        写入的 ParagraphMetricRow 列表，供段落曲线（§5.5）复用内存数据
        （避免再次查询，行内容与刚落库的数据一致）
    """
    from src.metrics.paragraph_metrics import compute_paragraph_metric_counts
    from src.metrics.paragraph_surface_tension import (
        robust_standardize_components,
        surface_tension_components,
        surface_tension_sigmoid,
        surface_tension_z_value,
    )

    counts_list = [
        compute_paragraph_metric_counts(span.text, tokens, lexicons)
        for span, tokens in zip(spans, tokenized, strict=True)
    ]
    z_components = robust_standardize_components([surface_tension_components(counts) for counts in counts_list])
    weights = settings.metrics.surface_tension_weights

    rows: list[ParagraphMetricRow] = []
    for span, counts, z_comp in zip(spans, counts_list, z_components, strict=True):
        paragraph_id = span.paragraph_id
        if paragraph_id is None:
            # insert_paragraphs 已校验段落身份完整，此处仅为类型收窄
            raise ValueError(f"段落指标写入失败：paragraph_id 未分配，paragraph_index={span.paragraph_index}")
        z_value = surface_tension_z_value(z_comp, weights)
        rows.append(
            ParagraphMetricRow(
                paragraph_id=paragraph_id,
                token_count=counts.token_count,
                char_count=counts.char_count,
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
                function_word_counts=counts.function_word_counts,
                semantic_category_counts=counts.semantic_category_counts,
                surface_tension_z=z_value,
                surface_tension=surface_tension_sigmoid(z_value),
            )
        )

    paragraph_repo = ParagraphRepository(session)
    paragraph_repo.insert_paragraph_metrics(run_id, rows)
    _commit_preprocess_writes(session, step="insert_paragraph_metrics")
    logger.info(f"inserted {len(rows)} paragraph metrics into db (run_id={run_id})")
    return rows


def _insert_paragraph_curves(
    session: Session,
    run_id: str,
    spans: list[ParagraphSpan],
    metric_rows: Sequence[ParagraphMetricRow],
) -> int:
    """
    计算并落库段落曲线（§5.5 / §9）

    段落坐标与字符权重从段落事实源读取（fetch_paragraph_rows），指标分子/分母
    复用 _insert_paragraph_metrics 的内存行（同一 run 刚写入，内容与库中一致）；
    total_chars 取段落 span 字符数之和。LOWESS 参数默认取 settings.metrics
    的 lowess_bandwidth / lowess_min_points（§9.3）。
    """
    from src.workflows.paragraph_curves import compute_paragraph_curves

    paragraph_repo = ParagraphRepository(session)
    paragraph_rows = paragraph_repo.fetch_paragraph_rows(run_id)
    total_chars = sum(span.char_count for span in spans)
    curve_rows = compute_paragraph_curves(
        paragraphs=paragraph_rows,
        metric_rows=metric_rows,
        total_chars=total_chars,
    )
    paragraph_repo.insert_paragraph_curves(run_id, curve_rows)
    _commit_preprocess_writes(session, step="insert_paragraph_curves")
    logger.info(f"inserted {len(curve_rows)} paragraph curves into db (run_id={run_id})")
    return len(curve_rows)


async def _generate_paragraph_embeddings(
    session: Session,
    run_id: str,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> int:
    """为 paragraphs 生成 embedding 落库；从 paragraphs 读不重切段，0行跳过。
    RAG 粒度固定自然段(仅 paragraph)。Args: session/run_id/emitter  Returns: embedding 数量
    """
    from src.agents.usage import build_token_usage_callback
    from src.models.local.embedding import EmbeddingClient
    from src.storage.models import AnalysisRun
    from src.storage.repositories.paragraph import (
        ParagraphEmbeddingRow,
        insert_paragraph_embeddings,
    )

    paragraph_refs = ParagraphRepository(session).fetch_paragraph_rows(run_id)
    if not paragraph_refs:
        logger.info("no paragraphs found for run_id={}, skip paragraph embeddings", run_id)
        return 0

    try:
        novel_id = session.execute(
            select(AnalysisRun.novel_id).where(AnalysisRun.run_id == run_id)
        ).scalar_one_or_none()
        embedding_client = EmbeddingClient(
            novel_id=novel_id if isinstance(novel_id, str) and novel_id else "unknown",
            token_usage_callback=build_token_usage_callback(session=session, run_id=run_id),
        )
    except ValueError as e:
        raise RuntimeError(
            "embedding client initialization failed during preprocess: "
            f"semantic text retrieval requires paragraph embeddings, error={e}"
        ) from e

    expected_dim = settings.models.paragraph_embedding.embedding_dim
    actual_dim = await embedding_client.detect_embedding_dimension()
    if actual_dim != expected_dim:
        raise ValueError(
            f"semantic text retrieval embedding dimension mismatch: configured={expected_dim}, actual={actual_dim}"
        )

    ensure_paragraph_embeddings_schema(session, expected_dim)
    _commit_preprocess_writes(session, step="ensure_embedding_schemas")

    paragraph_rows = await _generate_paragraph_embedding_rows(
        embedding_client,
        run_id,
        ParagraphEmbeddingRow,
        emitter=emitter,
    )
    if paragraph_rows:
        insert_paragraph_embeddings(session, run_id, paragraph_rows)
        _commit_preprocess_writes(session, step="insert_embedding_rows")
        logger.info(
            "inserted {} paragraph embeddings into db (run_id={})",
            len(paragraph_rows),
            run_id,
        )

    if emitter:
        await emitter(
            StreamEvent(
                action="complete",
                stage="preprocess",
                message="向量嵌入生成完成",
                sub_percent=100.0,
            )
        )

    return len(paragraph_rows)


async def _generate_paragraph_embedding_rows(
    embedding_client: Any,
    run_id: str,
    row_factory: Any,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> list[Any]:
    """生成 paragraph embedding 写入 DTO — 段落源 paragraphs(不重切，仅 paragraph_id+向量)，
    坐标从 paragraphs 读；批量 embed_texts 防单条退化。缺失 fail fast(防 readiness 假成功)，progress_callback 发 SSE。
    """
    from src.storage.db import get_session_factory
    from src.storage.repositories.paragraph_repository import ParagraphRepository

    with get_session_factory()() as session:
        paragraph_refs: list[tuple[int, int, int, int, int, int, int, str]] = []
        for row in ParagraphRepository(session).fetch_paragraph_rows(run_id):
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

    async def _emit_paragraph_embedding_progress(
        completed_batches: int,
        total_batches: int,
        total_items: int,
    ) -> None:
        """
        发射 preprocess 阶段 paragraph embedding 的批次进度

        """
        if emitter is None or total_batches <= 0:
            return

        sub_percent = (completed_batches / total_batches) * 100
        # current/total 在这里表达的是“已完成批次/总批次”，
        # message 再补充总 paragraph 数，避免和 章节 级 current/total 语义混淆
        await emitter(
            StreamEvent(
                action="progress",
                stage="preprocess",
                sub_stage="paragraph_embedding",
                current=completed_batches,
                total=total_batches,
                sub_percent=sub_percent,
                message=(f"段落向量落库准备 {completed_batches}/{total_batches} 批（共 {total_items} 段）"),
            )
        )

    paragraph_texts = [paragraph_text for _, _, _, _, _, _, _, paragraph_text in paragraph_refs]
    paragraph_embeddings = await embedding_client.embed_texts(
        paragraph_texts,
        progress_callback=_emit_paragraph_embedding_progress,
    )
    if len(paragraph_embeddings) != len(paragraph_refs):
        raise RuntimeError(
            "paragraph embedding result count mismatch: "
            f"expected {len(paragraph_refs)}, got {len(paragraph_embeddings)}"
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
    ), embedding in zip(
        paragraph_refs,
        paragraph_embeddings,
        strict=True,
    ):
        if not embedding:
            logger.error(
                "empty paragraph embedding detected: run_id={} chapter_id={} paragraph_index={}",
                run_id,
                chapter_id,
                paragraph_index,
            )
            missing_refs.append((chapter_id, paragraph_index))
            continue
        rows.append(
            row_factory(
                paragraph_id=paragraph_id,
                embedding_vector=embedding,
            )
        )
    if missing_refs:
        preview_refs = ", ".join(f"{chapter_id}:{paragraph_index}" for chapter_id, paragraph_index in missing_refs[:10])
        raise RuntimeError(
            "paragraph embeddings incomplete during preprocess: "
            f"run_id={run_id}, missing={preview_refs}, total={len(missing_refs)}"
        )
    return rows
