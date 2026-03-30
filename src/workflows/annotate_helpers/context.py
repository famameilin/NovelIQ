"""
标注辅助函数模块 - 上下文管理

创建时间: 2026-03-13
创建者: TraeAI
任务: 项目文件结构整理与拆解

修改历史:
- 2026-03-14: 从 cli.annotate_helpers 迁移，解决循环依赖
- 2026-03-14: 更新 RAGRetriever 初始化，使用 Repository 参数

说明: 本模块包含上下文管理相关的数据类和函数。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from src.config import settings
from src.config.schemas import ANNOTATION_CONFIG
from src.models.local.embedding import EmbeddingClient

if TYPE_CHECKING:
    from src.rag import RAGRetriever


class ChunkContext:
    """Chunk上下文数据类

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 统一字段命名，使用 prev_chunk_text 和 next_chunk_text

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: refactor-phase1-identity-extraction
    修改内容: 移除 character_appearances 字段（已迁移至 Phase 3）
    """

    def __init__(
        self,
        prev_chunk_text: str | None = None,
        active_entities_str: str | None = None,
        rag_evidence_str: str | None = None,
        known_aliases_str: str | None = None,
        next_chunk_text: str | None = None,
    ) -> None:
        self.prev_chunk_text = prev_chunk_text
        self.active_entities_str = active_entities_str
        self.rag_evidence_str = rag_evidence_str
        self.known_aliases_str = known_aliases_str
        self.next_chunk_text = next_chunk_text


def _init_rag_retriever(
    conn,
    novel_id: str,
    use_rag: bool,
    resume: bool,
    token_usage_callback,
    run_id: str | None = None,
) -> tuple[RAGRetriever | None, EmbeddingClient | None]:
    """初始化RAG检索器"""
    if not use_rag or not settings.rag.enabled:
        return None, None

    from src.rag import RAGRetriever
    from src.storage.repositories import GraphRepository

    logger.info("initializing RAG retriever")

    embedding_client: EmbeddingClient | None = None

    try:
        embedding_client = EmbeddingClient(
            token_usage_callback=token_usage_callback,
            novel_id=novel_id,
        )
    except Exception as e:
        logger.warning(f"embedding client initialization failed: {e}")

    graph_repo = GraphRepository(conn)
    rag_retriever = RAGRetriever(
        graph_repo=graph_repo,
        novel_id=novel_id,
        run_id=run_id,
        embedding_client=embedding_client if settings.rag.embedding_enabled else None,
        similarity_threshold=settings.rag.similarity_threshold,
        lookback_chunks=settings.rag.lookback_chunks,
    )

    return rag_retriever, embedding_client


def _prepare_chunk_context(
    conn,
    chunk_id: int,
    chunk_text: str,
    alias_map: dict[str, str],
    use_context_enhancement: bool,
    rag_retriever: RAGRetriever | None,
    run_id: str | None = None,
) -> ChunkContext:
    """准备chunk上下文

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: refactor-phase1-identity-extraction
    修改内容: 移除 character_appearances 数据获取（已迁移至 Phase 3）
    """
    from src.context import format_entities_for_prompt, get_active_entities
    from src.storage.repositories import ChunkRepository, GraphRepository

    context = ChunkContext()

    if not use_context_enhancement:
        logger.debug(
            "context enhancement disabled; skipping context for chunk_id={}",
            chunk_id,
        )
    elif not run_id:
        logger.warning(
            "context enhancement skipped due to empty run_id for chunk_id={}",
            chunk_id,
        )
    else:
        chunk_repo = ChunkRepository(conn)
        context.prev_chunk_text = chunk_repo.fetch_prev_chunk_text(run_id, chunk_id)
        context.next_chunk_text = chunk_repo.fetch_next_chunk_text(run_id, chunk_id)
        graph_repo = GraphRepository(conn)
        active_entities = get_active_entities(graph_repo, run_id, chunk_id, lookback=ANNOTATION_CONFIG.lookback)
        if active_entities:
            context.active_entities_str = format_entities_for_prompt(active_entities)

    if rag_retriever:
        context.known_aliases_str = rag_retriever.format_known_aliases_for_prompt()
        if settings.rag.level2_enabled:
            all_aliases = rag_retriever.get_known_aliases()
            if all_aliases:
                candidate_names = list(set(all_aliases.values()))[:5]
                context.rag_evidence_str = (
                    f"<Known_Alias_Candidates>{'、'.join(candidate_names)}</Known_Alias_Candidates>"
                )

    return context
