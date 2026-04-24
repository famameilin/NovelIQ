"""
标注辅助函数模块 - 上下文管理

创建时间: 2026-03-13
创建者: TraeAI
任务: 项目文件结构整理与拆解

修改历史:
- 2026-03-14: 从 cli.annotate_helpers 迁移，解决循环依赖
- 2026-03-14: 更新 DisambigContextProvider 初始化，使用 Repository 参数
- 2026-03-30: RAGRetriever → DisambigContextProvider，移除向量检索层
- 2026-04-10: 重新实现 Level 3 向量检索集成

说明: 本模块包含上下文管理相关的数据类和函数。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from src.config import settings
from src.knowledge.authority import KnowledgeGraphAuthorityService
from src.models.local.annotation.evidence_renderer import AnnotationPromptBlocks, render_annotation_prompt_blocks
from src.models.local.evidence_renderer_shared import render_active_entities_from_authority

if TYPE_CHECKING:
    from src.rag import DisambigContextProvider, EvidenceBundle


class ChunkContext:
    """Chunk上下文数据类

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 统一字段命名，使用 prev_chunk_text 和 next_chunk_text

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: refactor-phase1-identity-extraction
    修改内容: 移除 character_appearances 字段（已迁移至 Phase 3）

    修改时间: 2026-04-10
    修改者: TraeAI
    任务: implement-level3-vector-retrieval
    修改内容: 添加 vector_evidence_str 字段

    修改时间: 2026-04-16
    修改者: Codex
    任务: trim-legacy-string-evidence
    修改内容: 新增 annotation_prompt_blocks 语义入口，旧字符串字段降为兼容层

    修改时间: 2026-04-17
    修改者: Codex
    任务: trim-legacy-string-evidence
    修改内容: 删除遗留字符串字段和兼容属性，主链路统一使用 annotation_prompt_blocks
    """

    def __init__(
        self,
        prev_chunk_text: str | None = None,
        next_chunk_text: str | None = None,
        evidence_bundle: EvidenceBundle | None = None,
        annotation_prompt_blocks: AnnotationPromptBlocks | None = None,
        active_entities_fallback: str | None = None,
    ) -> None:
        self.prev_chunk_text = prev_chunk_text
        self.next_chunk_text = next_chunk_text
        self.evidence_bundle = evidence_bundle
        self.annotation_prompt_blocks = annotation_prompt_blocks
        self.active_entities_fallback = active_entities_fallback

    @property
    def prompt_active_entities(self) -> str | None:
        if self.annotation_prompt_blocks and self.annotation_prompt_blocks.active_entities is not None:
            return self.annotation_prompt_blocks.active_entities
        if self.active_entities_fallback is not None:
            return self.active_entities_fallback
        return None

    @property
    def prompt_disambig_context(self) -> str | None:
        if self.annotation_prompt_blocks and self.annotation_prompt_blocks.disambig_context is not None:
            return self.annotation_prompt_blocks.disambig_context
        return None

    @property
    def prompt_vector_evidence(self) -> str | None:
        if self.annotation_prompt_blocks and self.annotation_prompt_blocks.vector_evidence is not None:
            return self.annotation_prompt_blocks.vector_evidence
        return None


def _init_evidence_provider(
    conn,
    novel_id: str,
    use_context: bool,
    run_id: str | None = None,
) -> DisambigContextProvider | None:
    """初始化 evidence provider

    修改时间: 2026-04-10
    修改者: TraeAI
    任务: implement-level3-vector-retrieval
    修改内容: 支持 Level 3 向量检索，传入 session 和 embedding_client
    """
    if not use_context or not settings.rag.enabled:
        return None

    from src.rag import DisambigContextProvider
    from src.storage.repositories import GraphRepository

    logger.info("initializing evidence provider")

    graph_repo = GraphRepository(conn)

    embedding_client = None
    if settings.rag.embedding_enabled and settings.rag.level3_enabled:
        try:
            from src.models.local.embedding import EmbeddingClient

            embedding_client = EmbeddingClient(novel_id=novel_id)
            logger.info("Level 3 vector retrieval enabled and required")
        except ValueError as e:
            logger.error(
                "EmbeddingClient initialization failed; Level 3 is required and annotation will fail readiness "
                f"checks: {e}"
            )

    evidence_provider = DisambigContextProvider(
        graph_repo=graph_repo,
        novel_id=novel_id,
        run_id=run_id,
        lookback_chunks=settings.rag.lookback_chunks,
        session=conn,
        embedding_client=embedding_client,
        level1_enabled=settings.rag.level1_enabled,
        level2_enabled=settings.rag.level2_enabled,
        level3_enabled=settings.rag.level3_enabled,
        similarity_threshold=settings.rag.similarity_threshold,
        level3_top_k=settings.rag.level3_top_k,
    )

    return evidence_provider


def _extract_names_from_text(text: str) -> list[str]:
    """从文本中提取可能的人名候选（简化版：2-4字中文字符串）"""
    import re

    return re.findall(r"[\u4e00-\u9fff]{2,4}", text)


def _build_active_entities_prompt_from_authority(
    conn,
    run_id: str,
    chunk_id: int,
    lookback: int,
) -> str | None:
    """Reuse the authority-owned Level 2 contract even when the RAG provider is unavailable."""

    active_entities = KnowledgeGraphAuthorityService.from_session(conn).build_active_entity_view(
        run_id,
        current_chunk=chunk_id,
        lookback=lookback,
    )
    return render_active_entities_from_authority(active_entities)


def _prepare_chunk_context(
    conn,
    chunk_id: int,
    chunk_text: str,
    alias_map: dict[str, str],
    use_context_enhancement: bool,
    disambig_provider: DisambigContextProvider | None,
    run_id: str | None = None,
) -> ChunkContext:
    """准备chunk上下文（同步版本，不使用 Level 3）

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: refactor-phase1-identity-extraction
    修改内容: 移除 character_appearances 数据获取（已迁移至 Phase 3）
    """
    from src.storage.repositories import ChunkRepository

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
        lookback = settings.runtime.annotation.lookback
        context.active_entities_fallback = _build_active_entities_prompt_from_authority(
            conn,
            run_id,
            chunk_id,
            lookback=lookback,
        )

    if disambig_provider:
        names_in_chunk = _extract_names_from_text(chunk_text)
        context.evidence_bundle = disambig_provider.collect_evidence(
            names_in_chunk=names_in_chunk,
            current_chunk=chunk_id,
        )
        context.annotation_prompt_blocks = render_annotation_prompt_blocks(context.evidence_bundle)

    return context


async def _prepare_chunk_context_with_level3(
    conn,
    chunk_id: int,
    chunk_text: str,
    alias_map: dict[str, str],
    use_context_enhancement: bool,
    disambig_provider: DisambigContextProvider | None,
    run_id: str | None = None,
) -> ChunkContext:
    """准备chunk上下文（异步版本，支持 Level 3 向量检索）

    创建时间: 2026-04-10
    创建者: TraeAI
    任务: implement-level3-vector-retrieval
    说明: 异步版本，支持 Level 3 向量检索

    修改时间: 2026-04-23
    任务: level3-history-cutoff
    修改说明: annotation 阶段的 Level3 检索只允许查看当前 chunk 之前的历史。

    修改时间: 2026-04-24
    任务: llm-mention-rerank-chain
    修改说明: mention extraction/query 构造收口到 provider，workflow 只透传当前 chunk 取证上下文。
    """
    from src.storage.repositories import ChunkRepository

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
        lookback = settings.runtime.annotation.lookback
        context.active_entities_fallback = _build_active_entities_prompt_from_authority(
            conn,
            run_id,
            chunk_id,
            lookback=lookback,
        )

    if disambig_provider:
        names_in_chunk = _extract_names_from_text(chunk_text)
        if disambig_provider.requires_level3():
            if not disambig_provider.is_level3_available():
                raise RuntimeError("Level 3 vector retrieval is required but not available")
            context.evidence_bundle = await disambig_provider.collect_evidence_with_level3(
                names_in_chunk=names_in_chunk,
                current_chunk=chunk_id,
                context_text=chunk_text,
                exclude_chunk_ids=[chunk_id],
                max_chunk_id=chunk_id - 1,
            )
        elif disambig_provider.is_level3_available():
            context.evidence_bundle = await disambig_provider.collect_evidence_with_level3(
                names_in_chunk=names_in_chunk,
                current_chunk=chunk_id,
                context_text=chunk_text,
                exclude_chunk_ids=[chunk_id],
                max_chunk_id=chunk_id - 1,
            )
        else:
            context.evidence_bundle = disambig_provider.collect_evidence(
                names_in_chunk=names_in_chunk,
                current_chunk=chunk_id,
            )

        context.annotation_prompt_blocks = render_annotation_prompt_blocks(context.evidence_bundle)

    return context
