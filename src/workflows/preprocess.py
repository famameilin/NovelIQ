"""
创建时间: 2026-03-14
创建者: TraeAI
任务: 从 cli 模块提取核心业务逻辑到 workflows 模块

本模块从 src.cli.preprocess 提取核心业务逻辑，作为预处理流程的核心工作流模块。
包含文本清洗、分块、写入数据库，以及风格/文化指标计算等功能。

修改时间: 2026-03-14
修改者: TraeAI
任务: workflows 使用 Repository 模式重构
修改内容: 添加 run_id/session 参数支持，使用 ChunkRepository 替代直接调用 operations 函数

修改时间: 2026-03-15
修改者: TraeAI
任务: storage-layer-decoupling
修改内容: 移除向后兼容代码，只保留 Repository 模式

修改时间: 2026-04-09
修改者: TraeAI
任务: 重构其他 workflow 为 async
修改内容: run_preprocess 改为 async def，所有内部调用改为 await

修改时间: 2026-04-10
修改者: TraeAI
任务: implement-level3-vector-retrieval
修改内容: 添加 chunk embedding 生成功能
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import cast

from loguru import logger
from sqlalchemy.orm import Session

from src.api.models.events import StreamEvent
from src.chunking.chunker import chunk_documents
from src.config import settings
from src.ingest.reader import ingest_path
from src.preprocess.cleaning import normalize_text
from src.preprocess.tokenize import tokenize
from src.storage.repositories import ChunkRepository, ChunkStyleData
from src.storage.vector_schema import ensure_chunk_embeddings_schema


async def run_preprocess(
    source_path: Path,
    run_id: str,
    session: Session,
    metadata_path: Path | None = None,
    cache_path: Path | None = None,
    max_chars: int = 2000,
    overlap: int = 200,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> tuple[int, int, float]:
    """
    执行预处理流程。

    创建时间: 2025-03-11
    创建者: TraeAI
    任务: 预处理流程
    修改时间: 2026-03-13
    修改者: TraeAI
    任务: refactor-analysis-layer-functions
    修改内容: 重构函数，使用辅助函数拆解职责，确保函数行数不超过 200 行
    修改时间: 2026-03-14
    修改者: TraeAI
    任务: workflows 使用 Repository 模式重构
    修改内容: 添加 run_id/session 参数，支持 Repository 模式

    Args:
        source_path: 源文件路径
        run_id: 运行ID
        session: 数据库连接
        metadata_path: 元数据路径
        cache_path: 缓存路径
        max_chars: 最大字符数
        overlap: 重叠字符数

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

    use_semantic = settings.chunking.use_semantic_chunking
    if use_semantic:
        logger.info("启用语义分块")
    all_chunks = await chunk_documents(
        normalized_texts, max_chars=max_chars, overlap=overlap, use_semantic=use_semantic
    )

    total_chunks = len(all_chunks)
    total_chars = sum(len(chunk.text) for chunk in all_chunks)
    logger.info(f"chunked {total_chunks} chunks total_chars={total_chars}")

    chunk_repo.insert_chunks(run_id, all_chunks)
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
        )
        style_rows.append(style_data)

    chunk_repo.insert_chunk_style(run_id, style_rows)

    if settings.rag.embedding_enabled and settings.rag.level3_enabled:
        logger.info("generating chunk embeddings for Level 3 vector retrieval")
        await _generate_chunk_embeddings(session, run_id, all_chunks, emitter=emitter)

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


async def _generate_chunk_embeddings(
    session: Session,
    run_id: str,
    all_chunks: list,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> int:
    """
    为所有 chunk 生成 embedding 并存入数据库

    创建时间: 2026-04-10
    创建者: TraeAI
    任务: implement-level3-vector-retrieval
    说明: 为 Level 3 向量检索生成 chunk embedding

    Args:
        session: 数据库连接
        run_id: 运行ID
        all_chunks: chunk 列表
        emitter: 事件发射器

    Returns:
        生成的 embedding 数量
    """
    from src.models.local.embedding import EmbeddingClient
    from src.storage.repositories.chunk import insert_chunk_embeddings

    try:
        embedding_client = EmbeddingClient()
    except ValueError as e:
        logger.warning(f"EmbeddingClient initialization failed, skipping embedding generation: {e}")
        return 0

    expected_dim = settings.models.semantic_chunking.embedding_dim
    actual_dim = await embedding_client.detect_embedding_dimension()
    if actual_dim != expected_dim:
        raise ValueError(f"Level 3 embedding dimension mismatch: configured={expected_dim}, actual={actual_dim}")

    ensure_chunk_embeddings_schema(session, expected_dim)

    total_chunks = len(all_chunks)
    if emitter:
        await emitter(
            StreamEvent(
                action="start",
                stage="preprocess",
                message="生成向量嵌入",
                sub_percent=0.0,
            )
        )

    embeddings: list[tuple[int, list[float]]] = []
    for idx, chunk in enumerate(all_chunks):
        chunk_id = chunk.index
        if total_chunks > 1 and idx % 10 == 0:
            logger.info(f"Generating embedding for chunk {idx + 1}/{total_chunks}")
            if emitter:
                sub_percent = (idx / total_chunks) * 100
                await emitter(
                    StreamEvent(
                        action="progress",
                        stage="preprocess",
                        message=f"生成向量嵌入 {idx + 1}/{total_chunks}",
                        sub_percent=sub_percent,
                    )
                )

        try:
            embedding = await embedding_client.get_embedding(chunk.text, chunk_id=chunk_id)
            if embedding:
                embeddings.append((chunk_id, embedding))
        except Exception as e:
            logger.warning(f"Failed to generate embedding for chunk {chunk_id}: {e}")
            continue

    if embeddings:
        insert_chunk_embeddings(session, run_id, embeddings)
        logger.info(f"inserted {len(embeddings)} chunk embeddings into db (run_id={run_id})")

    if emitter:
        await emitter(
            StreamEvent(
                action="complete",
                stage="preprocess",
                message="向量嵌入生成完成",
                sub_percent=100.0,
            )
        )

    return len(embeddings)
