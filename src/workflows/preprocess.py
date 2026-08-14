"""
预处理流程核心工作流模块

包含文本清洗、分块、写入数据库，以及风格/文化指标计算等功能。


"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, cast

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.models.events import StreamEvent
from src.chunking.chunker import Chunk, chunk_documents_with_chapters
from src.config import settings
from src.ingest.reader import ingest_path
from src.preprocess.cleaning import normalize_text
from src.preprocess.tokenize import tokenize
from src.storage.repositories import ChapterRepository, ChunkRepository, ChunkStyleData
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
    """
    执行预处理流程

    Args:
        source_path: 源文件路径
        run_id: 运行ID
        session: 数据库连接
        metadata_path: 元数据路径

    Returns:
        Tuple[int, int, float]: (总块数, 总字符数, 耗时)
    """
    from src.workflows.preprocess_helpers import (
        _compute_chunk_style_metrics,
        _load_all_lexicons_for_preprocess,
    )

    start_time = time.time()

    if emitter:
        await emitter(StreamEvent(action="start", stage="preprocess", message="开始预处理", sub_percent=0.0))

    chunk_repo = ChunkRepository(session)
    if chunk_repo.is_preprocess_complete(run_id):
        logger.info(f"preprocess already complete for run_id={run_id}, skipping")
        return 0, 0, 0.0

    docs = ingest_path(source_path, metadata_path)
    if not docs:
        logger.warning(f"no documents found source={source_path}")
        return 0, 0, 0.0
    logger.info(f"loaded {len(docs)} documents from {source_path}")

    lexicon_dir = Path("data/lexicons")
    lexicons = _load_all_lexicons_for_preprocess(lexicon_dir)

    normalized_texts: list[str] = []
    for doc in docs:
        normalized = normalize_text(doc.text)
        normalized_texts.append(normalized)

    all_chunks, all_chapters = await chunk_documents_with_chapters(
        normalized_texts,
        emitter=emitter,
    )

    total_chunks = len(all_chunks)
    total_chars = sum(len(chunk.text) for chunk in all_chunks)
    logger.info(f"chunked {total_chunks} chunks total_chars={total_chars}")

    chapter_repo = ChapterRepository(session)
    chapter_repo.insert_chapters(run_id, all_chapters)
    _commit_preprocess_writes(session, step="insert_chapters")
    logger.info(f"inserted {len(all_chapters)} chapters into db (run_id={run_id})")

    chunk_repo.insert_chunks(run_id, all_chunks)
    _commit_preprocess_writes(session, step="insert_chunks")
    logger.info(f"inserted {total_chunks} chunks into db (run_id={run_id})")

    style_rows: list[ChunkStyleData] = []
    for idx, chunk in enumerate(all_chunks):
        if total_chunks > 1:
            logger.info(f"Processing chunk {idx + 1}/{total_chunks}")
        tokens = tokenize(chunk.text)

        style_data = _compute_chunk_style_metrics(
            chunk,
            tokens,
            cast(list[str], lexicons.get("sensory", [])),
            cast(list[str], lexicons.get("function_words", [])),
            cast(dict, lexicons.get("semantic_categories", {})),
            cast(list[str], lexicons.get("imagery", [])),
            cast(dict, lexicons.get("fight_terms", {})),
        )
        style_rows.append(style_data)

    chunk_repo.insert_chunk_style(run_id, style_rows)
    _commit_preprocess_writes(session, step="insert_chunk_style")

    if settings.models.paragraph_embedding.semantic_enabled:
        logger.info("generating paragraph embeddings for semantic text retrieval")
        await _generate_paragraph_embeddings(session, run_id, all_chunks, emitter=emitter)

    elapsed = time.time() - start_time
    logger.info(f"preprocess completed chunks={total_chunks} chars={total_chars} time={elapsed:.2f}s")
    logger.info("\n=== Preprocess Statistics ===")
    logger.info(f"Total chunks: {total_chunks}")
    logger.info(f"Total characters: {total_chars}")
    logger.info(f"Processing time: {elapsed:.2f}s")

    if emitter:
        await emitter(
            StreamEvent(action="complete", stage="preprocess", current=1, total=1, percent=100.0, sub_percent=100.0)
        )

    return total_chunks, total_chars, elapsed


def _commit_preprocess_writes(session: Session, *, step: str) -> None:
    """
    提交 preprocess 阶段的分段写入，及时释放事务锁

    preprocess 会连续写 chunks、chunk_style、paragraph_embeddings，这些表都外键关联 analysis_runs
          若整段预处理共用一个长事务，EventBus 另一条连接更新 analysis_runs 时可能被阻塞到 statement timeout
          因此这里在关键批量写入后立即提交，主动切断长事务
    """
    # 这里的 commit 目标是缩短锁持有时间，而不是改变业务原子性边界；
    # preprocess 本身已是可恢复阶段，分段提交比让状态写回超时更符合当前系统语义
    session.commit()
    logger.debug(f"Committed preprocess writes after step={step}")


async def _generate_paragraph_embeddings(
    session: Session,
    run_id: str,
    all_chunks: list[Chunk],
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> int:
    """
    为所有 chunk 内的自然段生成 embedding 并存入数据库

    RAG 检索粒度固定为一个自然段，只生成 paragraph embedding，不再生成 chunk embedding

    Args:
        session: 数据库连接
        run_id: 运行ID
        all_chunks: chunk 列表
        emitter: 事件发射器

    Returns:
        生成的 embedding 数量
    """
    from src.agents.usage import build_token_usage_callback
    from src.models.local.embedding import EmbeddingClient
    from src.storage.models import AnalysisRun
    from src.storage.repositories.chunk import (
        ParagraphEmbeddingRow,
        insert_paragraph_embeddings,
    )

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
            "semantic text retrieval embedding dimension mismatch: "
            f"configured={expected_dim}, actual={actual_dim}"
        )

    ensure_paragraph_embeddings_schema(session, expected_dim)
    _commit_preprocess_writes(session, step="ensure_embedding_schemas")

    paragraph_rows = await _generate_paragraph_embedding_rows(
        embedding_client,
        run_id,
        all_chunks,
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
    all_chunks: list[Chunk],
    row_factory: Any,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> list[Any]:
    """
    生成 paragraph embedding 写入 DTO

    RAG 检索粒度固定为一个自然段：段落分割统一走 chunker.split_paragraphs，
    不再按行（\n）切分，避免把同一自然段拆成多条证据

    复用 EmbeddingClient.embed_texts 批量接口，避免 paragraph 落库把预处理阶段退化成大量单条请求

    修改说明: paragraph embedding 缺失会阻断语义原文定位，这里采用 fail fast，
              避免 preprocess 成功但后续 readiness 永远失败

    修改说明: paragraph row 直接落显式的 local/global offset，不再继续写旧的歧义字段

    修改说明: 通过批量 embedding 的 progress_callback 发 SSE，前端可看到 paragraph 向量化的持续推进
    """
    from src.chunking.chunker import split_paragraphs

    paragraph_refs: list[tuple[int, int, int, int, int, int, str]] = []
    for chunk in all_chunks:
        for paragraph_index, (
            local_start_char,
            local_end_char,
            paragraph_text,
        ) in enumerate(split_paragraphs(chunk.text)):
            paragraph_refs.append(
                (
                    chunk.index,
                    paragraph_index,
                    local_start_char,
                    local_end_char,
                    chunk.start + local_start_char,
                    chunk.start + local_end_char,
                    paragraph_text,
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
        # message 再补充总 paragraph 数，避免和 chunk 级 current/total 语义混淆
        await emitter(
            StreamEvent(
                action="progress",
                stage="preprocess",
                sub_stage="paragraph_embedding",
                current=completed_batches,
                total=total_batches,
                sub_percent=sub_percent,
                message=(
                    f"段落向量落库准备 {completed_batches}/{total_batches}"
                    f" 批（共 {total_items} 段）"
                ),
            )
        )

    paragraph_texts = [paragraph_text for _, _, _, _, _, _, paragraph_text in paragraph_refs]
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
        chunk_id,
        paragraph_index,
        local_start_char,
        local_end_char,
        global_start_char,
        global_end_char,
        paragraph_text,
    ), embedding in zip(
        paragraph_refs,
        paragraph_embeddings,
        strict=True,
    ):
        if not embedding:
            logger.error(
                "empty paragraph embedding detected: run_id={} chunk_id={} paragraph_index={}",
                run_id,
                chunk_id,
                paragraph_index,
            )
            missing_refs.append((chunk_id, paragraph_index))
            continue
        rows.append(
            row_factory(
                chunk_id=chunk_id,
                paragraph_index=paragraph_index,
                paragraph_text=paragraph_text,
                local_start_char=local_start_char,
                local_end_char=local_end_char,
                global_start_char=global_start_char,
                global_end_char=global_end_char,
                embedding_vector=embedding,
            )
        )
    if missing_refs:
        preview_refs = ", ".join(f"{chunk_id}:{paragraph_index}" for chunk_id, paragraph_index in missing_refs[:10])
        raise RuntimeError(
            "paragraph embeddings incomplete during preprocess: "
            f"run_id={run_id}, missing={preview_refs}, total={len(missing_refs)}"
        )
    return rows
