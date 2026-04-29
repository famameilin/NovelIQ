"""
标注辅助函数模块 - 上下文管理


本模块包含上下文管理相关的数据类和函数

"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from loguru import logger

from src.api.models.events import StreamEvent
from src.config import TaskType, settings
from src.knowledge.authority import ActiveEntityContext, KnowledgeGraphAuthorityService
from src.models.local.annotation.evidence_renderer import AnnotationPromptBlocks, render_annotation_prompt_blocks
from src.models.local.character_reference_policy import collect_reference_slots_from_text
from src.models.local.evidence_renderer_shared import render_active_entities_from_authority

if TYPE_CHECKING:
    from src.rag import EvidenceBundle, EvidenceRequest, NarrativeEvidenceService
    from src.rag.evidence_contracts import EvidenceConsumer, EvidenceObjective


class ChunkContext:
    """Chunk上下文数据类




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
        phase4_request_template: EvidenceRequest | None = None,
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
        提供只读别名给仍在直接构造 ChunkContext 的低层测试；生产主路径统一读取 phase1_bundle
        """
        return self.phase1_bundle

    @property
    def annotation_prompt_blocks(self) -> AnnotationPromptBlocks | None:
        """
        提供只读别名给旧测试；生产主路径统一读取 phase1_prompt_blocks
        """
        return self.phase1_prompt_blocks


def _init_evidence_service(
    conn,
    novel_id: str,
    use_context: bool,
    run_id: str | None = None,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> NarrativeEvidenceService | None:
    """初始化 evidence service


    """
    if not use_context or not settings.rag.enabled:
        return None

    from src.rag import NarrativeEvidenceService
    from src.storage.repositories import GraphRepository

    logger.info("initializing narrative evidence service")

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

    evidence_service = NarrativeEvidenceService(
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

    return evidence_service


def _init_optional_mention_extractor(
    *,
    novel_id: str,
    session,
    run_id: str | None,
):
    """
    仅在 mention_extraction 配置完整时初始化 LLM extractor；未配置时保持规则 fallback 主链不变
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
    仅在 level3_rerank 配置完整时初始化模型 reranker；否则继续走确定性 rerank fallback
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
    对可选增强模型统一执行“未配置则禁用、配置不完整则报错、配置完整则初始化”的收口逻辑
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

    # 这里直接复用现有 BaseModelClient，避免为 mention extraction / rerank 再分叉一套 transport
    client = BaseModelClient(task_type=task_type, novel_id=novel_id, session=session)
    if run_id:
        client.set_runtime_context(novel_id, _build_optional_task_token_usage_callback(session, run_id, novel_id))
    logger.info("optional task model initialized: task_type={} model={}", task_type, task_settings.model)
    return client


def _build_optional_task_token_usage_callback(session, run_id: str, novel_id: str):
    """
    为 mention extraction / level3 rerank 复用主链 token_usage 落库方式，
          避免这两条可选增强链只发请求、不进统一统计账本
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
    统一从 authority 拉取活跃实体上下文，供 prompt fallback 和 Level3 seed_entities 复用，避免重复查询
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
    """Reuse the authority-owned Level 2 contract even when the RAG provider is unavailable"""

    active_entities = _build_active_entity_contexts_from_authority(conn, run_id, chunk_id, lookback)
    return render_active_entities_from_authority(active_entities)


def _collect_seed_entities(
    alias_map: dict[str, str] | None,
    active_entity_names: list[str],
    *,
    query_text: str | None = None,
    extra_names: list[str] | None = None,
) -> list[str]:
    """
    Level3 seed_entities 只允许来自可信源：chunk 内显式出现的 alias/canonical、
          authority active entities、调用方显式补充名；不能把整轮累计 alias_map 全量带进当前 chunk
    """
    seed_entities: list[str] = []
    normalized_query_text = (query_text or "").strip()
    for alias, canonical in (alias_map or {}).items():
        normalized_alias = str(alias).strip()
        normalized_canonical = str(canonical).strip()
        if not normalized_query_text:
            continue
        if normalized_alias and normalized_alias in normalized_query_text and normalized_alias not in seed_entities:
            seed_entities.append(normalized_alias)
        if (
            normalized_canonical
            and (
                normalized_canonical in normalized_query_text
                or (normalized_alias and normalized_alias in normalized_query_text)
            )
            and normalized_canonical not in seed_entities
        ):
            seed_entities.append(normalized_canonical)

    for entity_name in active_entity_names:
        normalized = str(entity_name).strip()
        if normalized and normalized not in seed_entities:
            seed_entities.append(normalized)

    for name in extra_names or []:
        normalized = str(name).strip()
        if normalized and normalized not in seed_entities:
            seed_entities.append(normalized)

    return seed_entities


def _collect_requested_names(
    alias_map: dict[str, str] | None,
    *,
    query_text: str | None = None,
    extra_names: list[str] | None = None,
) -> list[str]:
    """
    requested_names 只表达“当前 consumer 正在处理谁”，
          不应混入 Level2 active entities 这类仅用于 retrieval 扩锚的背景名

    """
    requested_names = _collect_seed_entities(
        alias_map,
        [],
        query_text=query_text,
    )
    normalized_query_text = (query_text or "").strip()
    if not normalized_query_text:
        return requested_names

    for name in extra_names or []:
        normalized = str(name).strip()
        if normalized and normalized in normalized_query_text and normalized not in requested_names:
            requested_names.append(normalized)

    return requested_names


def _build_evidence_request(
    *,
    consumer: EvidenceConsumer,
    objective: EvidenceObjective,
    query_text: str,
    requested_names: list[str],
    seed_entities: list[str],
    reference_slots: list[str] | None,
    background_entities: list[str] | None,
    chunk_id: int,
    max_chunk_id: int | None,
    allow_llm_query_expansion: bool,
    need_level1: bool = True,
    need_level2: bool = True,
    need_level3: bool = True,
):
    """
    workflow 侧只构造显式 EvidenceRequest；
          真实 annotation 主链统一走 `EvidenceRequest -> NarrativeEvidenceService.collect()`
    """
    from src.rag import EvidenceRequest

    return EvidenceRequest(
        consumer=consumer,
        objective=objective,
        query_text=query_text,
        requested_names=requested_names,
        seed_entities=seed_entities,
        reference_slots=list(reference_slots or []),
        background_entities=list(background_entities or []),
        current_chunk=chunk_id,
        max_chunk_id=max_chunk_id,
        exclude_chunk_ids=[chunk_id],
        need_level1=need_level1,
        need_level2=need_level2,
        need_level3=need_level3,
        allow_llm_query_expansion=allow_llm_query_expansion,
        top_k=settings.rag.level3_top_k,
        max_queries=settings.rag.level3_max_queries,
        model_rerank_query_max_chars=settings.rag.level3_model_rerank_query_max_chars,
    )


def _extract_active_entity_names(
    active_entities: list[ActiveEntityContext],
) -> list[str]:
    """
    修改说明: retrieval seed_entities 直接消费 authority 的结构化活跃实体视图；
              不再从 renderer 文本反解析名字，避免展示层文案反向污染取证边界
    """
    return [item.name for item in active_entities if str(item.name).strip()]


def _collect_evidence_sync(
    evidence_service: NarrativeEvidenceService,
    request: EvidenceRequest,
) -> EvidenceBundle:
    """
    无 Level3 的同步 annotation 路径也必须统一走 `NarrativeEvidenceService.collect(request)`，
          这样 request_meta/generation_meta/cache reuse 等语义才不会只在异步路径生效
          这里显式限制为“当前线程没有运行中事件循环”的同步场景；若已在 async 上下文中，应改走异步入口
    """

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(evidence_service.collect(request))
    raise RuntimeError(
        "Synchronous chunk context cannot call NarrativeEvidenceService.collect() inside a running event loop; "
        "use the async chunk-context path instead."
    )


def _prepare_chunk_context(
    conn,
    chunk_id: int,
    chunk_text: str,
    alias_map: dict[str, str],
    use_context_enhancement: bool,
    evidence_service: NarrativeEvidenceService | None,
    run_id: str | None = None,
) -> ChunkContext:
    """准备chunk上下文（同步版本，不使用 Level 3）



    """

    context = ChunkContext()
    active_entity_contexts: list[ActiveEntityContext] = []

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
        lookback = settings.runtime.annotation.lookback
        active_entity_contexts = _build_active_entity_contexts_from_authority(
            conn,
            run_id,
            chunk_id,
            lookback=lookback,
        )
        context.active_entities_fallback = render_active_entities_from_authority(active_entity_contexts)

    if evidence_service:
        active_entity_names = _extract_active_entity_names(active_entity_contexts)
        phase1_seed_entities = _collect_seed_entities(alias_map, active_entity_names, query_text=chunk_text)
        phase4_reference_slots = collect_reference_slots_from_text(chunk_text, chunk_id=chunk_id)
        include_phase2_evidence = settings.analysis.multi_phase_annotation.include_phase2_evidence

        phase1_request = _build_evidence_request(
            consumer="annotation_phase1",
            objective="identity",
            query_text=chunk_text,
            requested_names=_collect_requested_names(
                alias_map,
                query_text=chunk_text,
                extra_names=active_entity_names,
            ),
            seed_entities=phase1_seed_entities,
            reference_slots=[],
            background_entities=[],
            chunk_id=chunk_id,
            max_chunk_id=chunk_id - 1,
            allow_llm_query_expansion=False,
            need_level3=False,
        )

        context.phase1_bundle = _collect_evidence_sync(evidence_service, phase1_request)
        # 默认强伏笔路径已经切到 current-text-only，
        # 因此只有显式打开 include_phase2_evidence 时才为 Phase2 额外收集共享 evidence，
        # 避免在默认热路径上继续支付无效检索成本
        if include_phase2_evidence:
            phase2_seed_entities = _collect_seed_entities(None, active_entity_names)
            phase2_request = _build_evidence_request(
                consumer="annotation_phase2",
                objective="foreshadowing",
                query_text=chunk_text,
                requested_names=list(active_entity_names),
                seed_entities=phase2_seed_entities,
                reference_slots=[],
                background_entities=[],
                chunk_id=chunk_id,
                max_chunk_id=chunk_id - 1,
                allow_llm_query_expansion=False,
                need_level3=False,
            )
            context.phase2_bundle = _collect_evidence_sync(evidence_service, phase2_request)
        context.phase3_bundle = context.phase1_bundle
        # Phase4 的 consumer target 只能由当前 chunk 的 Phase1 known_characters 决定；
        # 这里先冻结空模板，避免历史活跃实体在真正取证前就放大 requested_names / seed_entities
        context.phase4_request_template = _build_evidence_request(
            consumer="annotation_phase4",
            objective="relation",
            query_text=chunk_text,
            requested_names=[],
            seed_entities=[],
            reference_slots=phase4_reference_slots,
            background_entities=[],
            chunk_id=chunk_id,
            max_chunk_id=chunk_id - 1,
            allow_llm_query_expansion=False,
            need_level3=False,
        )
        if context.phase1_bundle is not None:
            context.phase1_prompt_blocks = render_annotation_prompt_blocks(context.phase1_bundle)

    return context


async def _prepare_chunk_context_with_level3(
    conn,
    chunk_id: int,
    chunk_text: str,
    alias_map: dict[str, str],
    use_context_enhancement: bool,
    evidence_service: NarrativeEvidenceService | None,
    run_id: str | None = None,
) -> ChunkContext:
    """准备chunk上下文（异步版本，支持 Level 3 向量检索）

    异步版本，支持 Level 3 向量检索

    修改说明: annotation 阶段的 Level3 检索只允许查看当前 chunk 之前的历史

    修改说明: mention extraction/query 构造收口到 provider，workflow 只透传当前 chunk 取证上下文


    """

    context = ChunkContext()
    active_entity_contexts: list[ActiveEntityContext] = []

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
        lookback = settings.runtime.annotation.lookback
        active_entity_contexts = _build_active_entity_contexts_from_authority(
            conn,
            run_id,
            chunk_id,
            lookback=lookback,
        )
        context.active_entities_fallback = render_active_entities_from_authority(active_entity_contexts)

    if evidence_service:
        active_entity_names = _extract_active_entity_names(active_entity_contexts)
        phase4_reference_slots = collect_reference_slots_from_text(chunk_text, chunk_id=chunk_id)
        include_phase2_evidence = settings.analysis.multi_phase_annotation.include_phase2_evidence
        phase1_request = _build_evidence_request(
            consumer="annotation_phase1",
            objective="identity",
            query_text=chunk_text,
            requested_names=_collect_requested_names(
                alias_map,
                query_text=chunk_text,
                extra_names=active_entity_names,
            ),
            seed_entities=_collect_seed_entities(alias_map, active_entity_names, query_text=chunk_text),
            reference_slots=[],
            background_entities=[],
            chunk_id=chunk_id,
            max_chunk_id=chunk_id - 1,
            allow_llm_query_expansion=True,
        )
        phase3_request = _build_evidence_request(
            consumer="annotation_phase3",
            objective="identity",
            query_text=chunk_text,
            requested_names=_collect_requested_names(
                alias_map,
                query_text=chunk_text,
                extra_names=active_entity_names,
            ),
            seed_entities=_collect_seed_entities(alias_map, active_entity_names, query_text=chunk_text),
            reference_slots=[],
            background_entities=[],
            chunk_id=chunk_id,
            max_chunk_id=chunk_id - 1,
            allow_llm_query_expansion=True,
        )
        context.phase1_bundle = await evidence_service.collect(phase1_request)
        # 异步 Level3 路径与同步路径保持同一语义边界；
        # 默认不为 Phase2 收集共享 evidence，只有 targeted ablation 时才显式打开
        if include_phase2_evidence:
            phase2_request = _build_evidence_request(
                consumer="annotation_phase2",
                objective="foreshadowing",
                query_text=chunk_text,
                requested_names=list(active_entity_names),
                seed_entities=_collect_seed_entities(None, active_entity_names),
                reference_slots=[],
                background_entities=[],
                chunk_id=chunk_id,
                max_chunk_id=chunk_id - 1,
                allow_llm_query_expansion=False,
            )
            context.phase2_bundle = await evidence_service.collect(phase2_request)
        context.phase3_bundle = await evidence_service.collect(phase3_request)
        # Phase4 的 consumer target 只能由当前 chunk 的 Phase1 known_characters 决定；
        # 这里先冻结空模板，避免历史活跃实体在真正取证前就放大 requested_names / seed_entities
        context.phase4_request_template = _build_evidence_request(
            consumer="annotation_phase4",
            objective="relation",
            query_text=chunk_text,
            requested_names=[],
            seed_entities=[],
            reference_slots=phase4_reference_slots,
            background_entities=[],
            chunk_id=chunk_id,
            max_chunk_id=chunk_id - 1,
            allow_llm_query_expansion=False,
        )
        if context.phase1_bundle is not None:
            context.phase1_prompt_blocks = render_annotation_prompt_blocks(context.phase1_bundle)

    return context
