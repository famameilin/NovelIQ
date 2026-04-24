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

import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, cast

from loguru import logger
from sqlalchemy.orm import Session

from src.api.models.events import StreamEvent
from src.chunking.chunker import Chunk, chunk_documents
from src.config import settings
from src.ingest.reader import ingest_path
from src.preprocess.cleaning import normalize_text
from src.preprocess.tokenize import tokenize
from src.storage.repositories import ChunkRepository, ChunkStyleData
from src.storage.vector_schema import (
    ensure_chunk_embeddings_schema,
    ensure_paragraph_embeddings_schema,
)


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

    修改时间: 2026-04-20
    修改者: Codex (GPT-5)
    任务: fix-preprocess-transaction-boundary
    修改内容: 将 chunks/style/embedding 写入切成短事务，避免长事务阻塞 analysis_runs 状态写回

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
        )
        style_rows.append(style_data)

    chunk_repo.insert_chunk_style(run_id, style_rows)
    _commit_preprocess_writes(session, step="insert_chunk_style")

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


def _commit_preprocess_writes(session: Session, *, step: str) -> None:
    """
    提交 preprocess 阶段的分段写入，及时释放事务锁。

    创建时间: 2026-04-20
    创建者: Codex (GPT-5)
    任务: fix-preprocess-transaction-boundary
    说明: preprocess 会连续写 chunks、chunk_style、chunk_embeddings，这些表都外键关联 analysis_runs。
          若整段预处理共用一个长事务，EventBus 另一条连接更新 analysis_runs 时可能被阻塞到 statement timeout。
          因此这里在关键批量写入后立即提交，主动切断长事务。
    """
    # 中文注释：这里的 commit 目标是缩短锁持有时间，而不是改变业务原子性边界；
    # preprocess 本身已是可恢复阶段，分段提交比让状态写回超时更符合当前系统语义。
    session.commit()
    logger.debug(f"Committed preprocess writes after step={step}")


async def _generate_chunk_embeddings(
    session: Session,
    run_id: str,
    all_chunks: list[Chunk],
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> int:
    """
    为所有 chunk 生成 embedding 并存入数据库

    创建时间: 2026-04-10
    创建者: TraeAI
    任务: implement-level3-vector-retrieval
    说明: 为 Level 3 向量检索生成 chunk embedding

    修改时间: 2026-04-20
    修改者: Codex (GPT-5)
    任务: fix-preprocess-transaction-boundary
    修改内容: 在 schema 准备后和 embedding 落库后及时提交，避免 embedding 长阶段阻塞 analysis_runs 状态写回

    修改时间: 2026-04-24
    任务: level3-paragraph-rerank
    修改内容: 同步生成 paragraph_embeddings，供 Level3 在 chunk 粗召回结果内做局部 evidence rerank

    修改时间: 2026-04-24
    任务: fix-level3-embedding-partial-write
    修改内容: chunk embedding 也改为 fail fast；任何 chunk 缺失向量都直接中断 preprocess，
              避免留下粗召回范围不完整、却仍被 readiness 误判为可用的 run

    修改时间: 2026-04-24
    任务: fix-paragraph-failfast-atomicity
    修改内容: paragraph rows 先完整生成，再统一执行 chunk/paragraph 向量落库；
              避免 paragraph 失败时 session 中残留 chunk-only 向量写入

    Args:
        session: 数据库连接
        run_id: 运行ID
        all_chunks: chunk 列表
        emitter: 事件发射器

    Returns:
        生成的 embedding 数量
    """
    from src.models.local.embedding import EmbeddingClient
    from src.storage.repositories.chunk import (
        ParagraphEmbeddingRow,
        insert_chunk_embeddings,
        insert_paragraph_embeddings,
    )

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
    ensure_paragraph_embeddings_schema(session, expected_dim)
    _commit_preprocess_writes(session, step="ensure_embedding_schemas")

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
    failed_chunk_ids: list[int] = []
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
            if not embedding:
                logger.error("empty chunk embedding detected: run_id={} chunk_id={}", run_id, chunk_id)
                failed_chunk_ids.append(chunk_id)
                continue
            embeddings.append((chunk_id, embedding))
        except Exception as e:
            logger.error("failed to generate chunk embedding: run_id={} chunk_id={} error={}", run_id, chunk_id, e)
            failed_chunk_ids.append(chunk_id)
            continue

    if failed_chunk_ids:
        preview_ids = ", ".join(str(chunk_id) for chunk_id in failed_chunk_ids[:10])
        raise RuntimeError(
            "chunk embeddings incomplete during preprocess: "
            f"run_id={run_id}, missing={preview_ids}, total={len(failed_chunk_ids)}"
        )

    paragraph_rows = await _generate_paragraph_embedding_rows(
        embedding_client,
        run_id,
        all_chunks,
        ParagraphEmbeddingRow,
    )
    # 中文注释：先把 paragraph rows 全部准备好，再开始任何向量表 DML；
    # 这样 paragraph fail fast 时，当前 session 不会留下 chunk-only 半成品写入。
    if embeddings:
        insert_chunk_embeddings(session, run_id, embeddings)
    if paragraph_rows:
        insert_paragraph_embeddings(session, run_id, paragraph_rows)

    if embeddings or paragraph_rows:
        _commit_preprocess_writes(session, step="insert_embedding_rows")
        logger.info(
            "inserted {} chunk embeddings and {} paragraph embeddings into db (run_id={})",
            len(embeddings),
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

    return len(embeddings)


def _split_chunk_paragraphs(chunk: Chunk) -> list[tuple[int, int, str]]:
    """
    将 chunk 文本拆成 chunk 内 paragraph，并保留 chunk 内字符范围。

    创建时间: 2026-04-24
    任务: level3-paragraph-rerank
    说明: 当前 chunks 表未持久化全文 char_offset，因此这里的 start/end 明确定义为 chunk 内 offset；
          后续若补齐全文 offset，可在不改变 paragraph_index 主键的前提下增加全局范围字段。
    """
    if not chunk.text.strip():
        return []

    paragraphs: list[tuple[int, int, str]] = []
    start = 0
    for match in re.finditer(r"\n+", chunk.text):
        end = match.start()
        raw_text = chunk.text[start:end]
        stripped_text = raw_text.strip()
        if stripped_text:
            leading_ws = len(raw_text) - len(raw_text.lstrip())
            trailing_ws = len(raw_text.rstrip())
            paragraphs.append((start + leading_ws, start + trailing_ws, stripped_text))
        start = match.end()

    if start < len(chunk.text):
        raw_text = chunk.text[start:]
        stripped_text = raw_text.strip()
        if stripped_text:
            leading_ws = len(raw_text) - len(raw_text.lstrip())
            trailing_ws = len(raw_text.rstrip())
            paragraphs.append((start + leading_ws, start + trailing_ws, stripped_text))

    if paragraphs:
        return paragraphs
    return [(0, len(chunk.text), chunk.text.strip())]


async def _generate_paragraph_embedding_rows(
    embedding_client: Any,
    run_id: str,
    all_chunks: list[Chunk],
    row_factory: Any,
) -> list[Any]:
    """
    生成 paragraph embedding 写入 DTO。

    创建时间: 2026-04-24
    任务: level3-paragraph-rerank
    说明: 复用 EmbeddingClient.embed_texts 批量接口，避免 paragraph 落库把预处理阶段退化成大量单条请求。

    修改时间: 2026-04-24
    任务: fix-paragraph-embedding-partial-write
    修改说明: paragraph embedding 缺失已是 Level3 硬故障，这里改为 fail fast，
              避免 preprocess 成功但后续 readiness 永远失败。
    """
    paragraph_refs: list[tuple[int, int, int, int, str]] = []
    for chunk in all_chunks:
        for paragraph_index, (start_char, end_char, paragraph_text) in enumerate(_split_chunk_paragraphs(chunk)):
            paragraph_refs.append((chunk.index, paragraph_index, start_char, end_char, paragraph_text))

    if not paragraph_refs:
        return []

    paragraph_texts = [paragraph_text for _, _, _, _, paragraph_text in paragraph_refs]
    paragraph_embeddings = await embedding_client.embed_texts(paragraph_texts)
    if len(paragraph_embeddings) != len(paragraph_refs):
        raise RuntimeError(
            "paragraph embedding result count mismatch: "
            f"expected {len(paragraph_refs)}, got {len(paragraph_embeddings)}"
        )

    rows = []
    missing_refs: list[tuple[int, int]] = []
    for (chunk_id, paragraph_index, start_char, end_char, paragraph_text), embedding in zip(
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
                start_char=start_char,
                end_char=end_char,
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
