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

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from loguru import logger

from src.api.models.events import StreamEvent
from src.config import TaskType, settings
from src.knowledge.authority import ActiveEntityContext, KnowledgeGraphAuthorityService
from src.models.local.annotation.evidence_renderer import AnnotationPromptBlocks, render_annotation_prompt_blocks
from src.models.local.evidence_renderer_shared import render_active_entities_from_authority
from src.rag.level3_contracts import Level3Objective, build_level3_request_fingerprint

if TYPE_CHECKING:
    from src.rag import DisambigContextProvider, EvidenceBundle, Level3Request


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

    修改时间: 2026-04-25
    修改者: Codex
    任务: level3-intent-phase-split
    修改内容: 改为显式 phase-scoped bundles；Phase1 prompt 只消费 phase1_prompt_blocks，
              Phase2/3/4 由各自 bundle 独立透传。
    """

    def __init__(
        self,
        prev_chunk_text: str | None = None,
        next_chunk_text: str | None = None,
        phase1_bundle: EvidenceBundle | None = None,
        phase2_bundle: EvidenceBundle | None = None,
        phase3_bundle: EvidenceBundle | None = None,
        phase4_bundle: EvidenceBundle | None = None,
        phase1_prompt_blocks: AnnotationPromptBlocks | None = None,
        active_entities_fallback: str | None = None,
        phase4_request_template: Level3Request | None = None,
        evidence_bundle: EvidenceBundle | None = None,
        annotation_prompt_blocks: AnnotationPromptBlocks | None = None,
    ) -> None:
        self.prev_chunk_text = prev_chunk_text
        self.next_chunk_text = next_chunk_text
        self.phase1_bundle = phase1_bundle or evidence_bundle
        self.phase2_bundle = phase2_bundle
        self.phase3_bundle = phase3_bundle or self.phase1_bundle
        self.phase4_bundle = phase4_bundle
        self.phase1_prompt_blocks = phase1_prompt_blocks or annotation_prompt_blocks
        self.active_entities_fallback = active_entities_fallback
        self.phase4_request_template = phase4_request_template

    @property
    def prompt_active_entities(self) -> str | None:
        if self.phase1_prompt_blocks and self.phase1_prompt_blocks.active_entities is not None:
            return self.phase1_prompt_blocks.active_entities
        if self.active_entities_fallback is not None:
            return self.active_entities_fallback
        return None

    @property
    def prompt_disambig_context(self) -> str | None:
        if self.phase1_prompt_blocks and self.phase1_prompt_blocks.disambig_context is not None:
            return self.phase1_prompt_blocks.disambig_context
        return None

    @property
    def prompt_vector_evidence(self) -> str | None:
        if self.phase1_prompt_blocks and self.phase1_prompt_blocks.vector_evidence is not None:
            return self.phase1_prompt_blocks.vector_evidence
        return None

    @property
    def evidence_bundle(self) -> EvidenceBundle | None:
        """
        创建时间: 2026-04-25
        任务: level3-intent-phase-split
        说明: 提供只读别名给仍在直接构造 ChunkContext 的低层测试；生产主路径统一读取 phase1_bundle。
        """
        return self.phase1_bundle

    @property
    def annotation_prompt_blocks(self) -> AnnotationPromptBlocks | None:
        """
        创建时间: 2026-04-25
        任务: level3-intent-phase-split
        说明: 提供只读别名给旧测试；生产主路径统一读取 phase1_prompt_blocks。
        """
        return self.phase1_prompt_blocks


def _init_evidence_provider(
    conn,
    novel_id: str,
    use_context: bool,
    run_id: str | None = None,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> DisambigContextProvider | None:
    """初始化 evidence provider

    修改时间: 2026-04-10
    修改者: TraeAI
    任务: implement-level3-vector-retrieval
    修改内容: 支持 Level 3 向量检索，传入 session 和 embedding_client

    修改时间: 2026-04-24
    任务: level3-progress-sse
    修改内容: 将标注流程 emitter 传入 evidence provider，让 Level3/mention 长耗时阶段能推送 SSE 进度。
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

    mention_extractor = _init_optional_mention_extractor(novel_id=novel_id, session=conn, run_id=run_id)
    level3_reranker = _init_optional_level3_reranker(novel_id=novel_id, session=conn, run_id=run_id)

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
        mention_extractor=mention_extractor,
        level3_reranker=level3_reranker,
        progress_emitter=emitter,
    )

    return evidence_provider


def _init_optional_mention_extractor(
    *,
    novel_id: str,
    session,
    run_id: str | None,
):
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: 仅在 mention_extraction 配置完整时初始化 LLM extractor；未配置时保持规则 fallback 主链不变。
    """
    model_client = _build_optional_task_model_client(
        "mention_extraction",
        enabled=settings.rag.mention_extraction_enabled,
        novel_id=novel_id,
        session=session,
        run_id=run_id,
    )
    if model_client is None:
        return None

    from src.rag.mention_extraction_llm import LLMPersonMentionExtractor

    return LLMPersonMentionExtractor(
        model_client,
        enable_thinking=settings.thinking.mention_extraction,
    )


def _init_optional_level3_reranker(
    *,
    novel_id: str,
    session,
    run_id: str | None,
):
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: 仅在 level3_rerank 配置完整时初始化模型 reranker；否则继续走确定性 rerank fallback。
    """
    model_client = _build_optional_task_model_client(
        "level3_rerank",
        enabled=settings.rag.level3_rerank_enabled,
        novel_id=novel_id,
        session=session,
        run_id=run_id,
    )
    if model_client is None:
        return None

    from src.rag.model_rerank_llm import LLMLevel3Reranker

    return LLMLevel3Reranker(
        model_client,
        enable_thinking=settings.thinking.level3_rerank,
    )


def _build_optional_task_model_client(
    task_type: TaskType,
    *,
    enabled: bool,
    novel_id: str,
    session,
    run_id: str | None,
):
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: 对可选增强模型统一执行“未配置则禁用、配置不完整则报错、配置完整则初始化”的收口逻辑。
    """
    if not enabled:
        logger.info("optional task model disabled by rag switch: task_type={}", task_type)
        return None

    task_settings = getattr(settings.models, task_type)
    config_keys = ("base_url", "model", "api_key", "timeout_s")
    has_any_runtime_config = any(getattr(task_settings, key) is not None for key in config_keys)
    if not has_any_runtime_config:
        raise RuntimeError(f"optional task model enabled but config is absent: task_type={task_type}")

    if task_settings.base_url is None or task_settings.model is None:
        raise RuntimeError(
            f"optional task model config incomplete: task_type={task_type} "
            f"base_url={task_settings.base_url!r} model={task_settings.model!r}"
        )

    from src.models.local.base import BaseModelClient

    # 中文注释：这里直接复用现有 BaseModelClient，避免为 mention extraction / rerank 再分叉一套 transport。
    client = BaseModelClient(task_type=task_type, novel_id=novel_id, session=session)
    if run_id:
        client.set_runtime_context(novel_id, _build_optional_task_token_usage_callback(session, run_id, novel_id))
    logger.info("optional task model initialized: task_type={} model={}", task_type, task_settings.model)
    return client


def _build_optional_task_token_usage_callback(session, run_id: str, novel_id: str):
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-audit
    说明: 为 mention extraction / level3 rerank 复用主链 token_usage 落库方式，
          避免这两条可选增强链只发请求、不进统一统计账本。
    """
    from src.storage.repositories import StatsRepository

    def _token_usage_callback(
        cb_novel_id: str,
        callback_task_type: str,
        call_type: str,
        model: str,
        prompt_tokens: int,
        total_tokens: int,
        completion_tokens: int | None,
        chunk_id: int | None,
    ) -> None:
        stats_repo = StatsRepository(session)
        stats_repo.insert_token_usage(
            run_id,
            cb_novel_id or novel_id,
            callback_task_type,
            call_type,
            model,
            prompt_tokens,
            total_tokens,
            completion_tokens,
            chunk_id,
        )

    return _token_usage_callback


def _extract_names_from_text(text: str) -> list[str]:
    """从文本中提取可能的人名候选（简化版：2-4字中文字符串）"""
    import re

    return re.findall(r"[\u4e00-\u9fff]{2,4}", text)


def _build_active_entity_contexts_from_authority(
    conn,
    run_id: str,
    chunk_id: int,
    lookback: int,
) -> list[ActiveEntityContext]:
    """
    创建时间: 2026-04-25
    任务: level3-intent-phase-split
    说明: 统一从 authority 拉取活跃实体上下文，供 prompt fallback 和 Level3 seed_entities 复用，避免重复查询。
    """

    return KnowledgeGraphAuthorityService.from_session(conn).build_active_entity_view(
        run_id,
        current_chunk=chunk_id,
        lookback=lookback,
    )


def _build_active_entities_prompt_from_authority(
    conn,
    run_id: str,
    chunk_id: int,
    lookback: int,
) -> str | None:
    """Reuse the authority-owned Level 2 contract even when the RAG provider is unavailable."""

    active_entities = _build_active_entity_contexts_from_authority(conn, run_id, chunk_id, lookback)
    return render_active_entities_from_authority(active_entities)


def _collect_seed_entities(
    alias_map: dict[str, str] | None,
    active_entity_names: list[str],
    *,
    extra_names: list[str] | None = None,
) -> list[str]:
    """
    创建时间: 2026-04-25
    任务: level3-intent-phase-split
    说明: Level3 seed_entities 只允许来自可信源：alias_map、authority active entities、调用方显式补充名。
    """
    seed_entities: list[str] = []
    for name in list((alias_map or {}).keys()) + list((alias_map or {}).values()):
        normalized = str(name).strip()
        if normalized and normalized not in seed_entities:
            seed_entities.append(normalized)

    for entity_name in active_entity_names:
        normalized = str(entity_name).strip()
        if normalized and normalized not in seed_entities:
            seed_entities.append(normalized)

    for name in extra_names or []:
        normalized = str(name).strip()
        if normalized and normalized not in seed_entities:
            seed_entities.append(normalized)

    return seed_entities


def _extract_active_entity_names_from_prompt(active_entities_prompt: str | None) -> list[str]:
    """
    创建时间: 2026-04-25
    任务: level3-intent-phase-split
    说明: 从 authority renderer 的活跃实体区段里提取名字，供 Level3Request.seed_entities 复用；
          这样 workflow 不需要为了拿名字再额外查一次 authority。
    """
    if not active_entities_prompt:
        return []

    names: list[str] = []
    for line in active_entities_prompt.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        candidate = stripped[2:].split("（", 1)[0].split(":", 1)[0].strip()
        if candidate and candidate not in names:
            names.append(candidate)
    return names


def _build_level3_request(
    *,
    objective: Level3Objective,
    query_text: str,
    seed_entities: list[str],
    chunk_id: int,
    max_chunk_id: int | None,
    allow_llm_query_expansion: bool,
) -> Level3Request:
    """
    创建时间: 2026-04-25
    任务: level3-intent-phase-split
    说明: 统一从 workflow 入口构造显式 Level3Request，避免各 phase 再靠弱语义 kwargs 猜测意图。
    """
    from src.rag import Level3Request

    return Level3Request(
        objective=objective,
        query_text=query_text,
        seed_entities=seed_entities,
        current_chunk=chunk_id,
        max_chunk_id=max_chunk_id,
        exclude_chunk_ids=[chunk_id],
        allow_llm_query_expansion=allow_llm_query_expansion,
        top_k=settings.rag.level3_top_k,
        max_queries=settings.rag.level3_max_queries,
    )


async def _collect_phase_bundle(
    disambig_provider: DisambigContextProvider,
    request: Level3Request,
) -> EvidenceBundle:
    """
    创建时间: 2026-04-25
    任务: level3-intent-phase-split
    说明: workflow 侧只声明 request；provider 决定走 Level1/2 还是 Level1/2/3 主链，不再手写参数拼装。
    """
    if disambig_provider.requires_level3():
        if not disambig_provider.is_level3_available():
            raise RuntimeError("Level 3 vector retrieval is required but not available")
        return await disambig_provider.collect_evidence_with_level3(request)

    if disambig_provider.is_level3_available():
        return await disambig_provider.collect_evidence_with_level3(request)

    return disambig_provider.collect_evidence(
        names_in_chunk=request.seed_entities,
        current_chunk=request.current_chunk,
    )


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
        active_entity_names = _extract_active_entity_names_from_prompt(context.active_entities_fallback)
        phase1_request = _build_level3_request(
            objective="identity",
            query_text=chunk_text,
            seed_entities=_collect_seed_entities(alias_map, active_entity_names),
            chunk_id=chunk_id,
            max_chunk_id=chunk_id - 1,
            allow_llm_query_expansion=True,
        )
        phase2_request = _build_level3_request(
            objective="foreshadowing",
            query_text=chunk_text,
            seed_entities=_collect_seed_entities(None, active_entity_names),
            chunk_id=chunk_id,
            max_chunk_id=chunk_id - 1,
            allow_llm_query_expansion=False,
        )
        context.phase1_bundle = disambig_provider.collect_evidence(
            names_in_chunk=phase1_request.seed_entities,
            current_chunk=chunk_id,
        )
        context.phase2_bundle = disambig_provider.collect_evidence(
            names_in_chunk=phase2_request.seed_entities,
            current_chunk=chunk_id,
        )
        context.phase3_bundle = context.phase1_bundle
        context.phase4_request_template = _build_level3_request(
            objective="relation",
            query_text=chunk_text,
            seed_entities=_collect_seed_entities(None, active_entity_names),
            chunk_id=chunk_id,
            max_chunk_id=chunk_id - 1,
            allow_llm_query_expansion=False,
        )
        context.phase1_prompt_blocks = render_annotation_prompt_blocks(context.phase1_bundle)

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
        active_entity_names = _extract_active_entity_names_from_prompt(context.active_entities_fallback)

        phase1_request = _build_level3_request(
            objective="identity",
            query_text=chunk_text,
            seed_entities=_collect_seed_entities(alias_map, active_entity_names),
            chunk_id=chunk_id,
            max_chunk_id=chunk_id - 1,
            allow_llm_query_expansion=True,
        )
        phase2_request = _build_level3_request(
            objective="foreshadowing",
            query_text=chunk_text,
            seed_entities=_collect_seed_entities(None, active_entity_names),
            chunk_id=chunk_id,
            max_chunk_id=chunk_id - 1,
            allow_llm_query_expansion=False,
        )
        phase3_request = _build_level3_request(
            objective="identity",
            query_text=chunk_text,
            seed_entities=_collect_seed_entities(alias_map, active_entity_names),
            chunk_id=chunk_id,
            max_chunk_id=chunk_id - 1,
            allow_llm_query_expansion=True,
        )
        context.phase1_bundle = await _collect_phase_bundle(disambig_provider, phase1_request)
        context.phase2_bundle = await _collect_phase_bundle(disambig_provider, phase2_request)
        if (
            build_level3_request_fingerprint(phase1_request)
            == build_level3_request_fingerprint(phase3_request)
        ):
            context.phase3_bundle = context.phase1_bundle
        else:
            context.phase3_bundle = await _collect_phase_bundle(disambig_provider, phase3_request)
        context.phase4_request_template = _build_level3_request(
            objective="relation",
            query_text=chunk_text,
            seed_entities=_collect_seed_entities(None, active_entity_names),
            chunk_id=chunk_id,
            max_chunk_id=chunk_id - 1,
            allow_llm_query_expansion=False,
        )
        context.phase1_prompt_blocks = render_annotation_prompt_blocks(context.phase1_bundle)

    return context
