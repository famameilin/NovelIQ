"""
创建时间: 2025-03-12
创建者: TraeAI
任务: RAG 检索器实现

修改时间: 2026-03-13
修改者: TraeAI
修改内容: 将函数内部的导入语句移到文件顶部

修改时间: 2026-03-14
修改者: TraeAI
任务: metrics-repository-refactor
修改内容: 重构为使用 Repository 模式

修改时间: 2026-03-30
修改者: TraeAI
任务: 重命名 RAGRetriever → DisambigContextProvider，移除向量检索层

修改时间: 2026-04-10
修改者: TraeAI
任务: implement-level3-vector-retrieval
修改内容: 重新实现 Level3VectorEvidence，集成到 DisambigContextProvider

修改时间: 2026-04-17
修改者: TraeAI
任务: refactor/split-provider-bundle-renderer
修改内容: 删除 retrieve/retrieve_with_level3 废弃接口和 DisambigResult，
    将 build_graph_feedback_hint 迁移至 disambiguation renderer

修改时间: 2026-04-17
修改者: Codex
任务: split-provider-renderer-tail
修改内容: 删除 provider 内残留的 Level3 prompt 格式化逻辑，彻底收回为纯取证层

修改时间: 2026-04-21
修改者: Codex
任务: emotion-rag-evidence-provider
修改内容: 在统一 semantic_evidence 主路径内补充 emotion exemplar 证据，供 Phase1 情绪判断复用

说明: 本模块提供证据收集功能（Provider 层），支持三级证据：
- Level1: 别名表精确匹配
- Level2: 活跃实体候选
- Level3: 向量语义相似度检索
输出统一 EvidenceBundle，由下游 renderer 渲染为 prompt 内容。
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import TYPE_CHECKING

from loguru import logger

from src.api.models.events import StreamEvent
from src.config import settings
from src.knowledge.authority import KnowledgeGraphAuthorityService
from src.rag.authority import Level1AuthorityProvider
from src.rag.evidence_bundle_builder import EvidenceBundleBuilder
from src.rag.evidence_types import EvidenceBundle, Level1AuthoritySnapshot
from src.rag.level1_alias import AliasLookup
from src.rag.level2_active_entities import ActiveEntityLookup
from src.rag.level3_contracts import Level3QueryPlan, Level3Request
from src.rag.level3_vector import Level3NotReadyError, Level3VectorEvidence
from src.rag.mention_extraction_service import MentionExtractionService, PersonMentionExtractor
from src.rag.mention_extraction_types import MentionExtractionRequest, PersonMention
from src.rag.mention_rerank import rerank_mention_level3_results
from src.rag.model_rerank import Level3ModelReranker, try_model_rerank_level3_results

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.models.local.embedding import EmbeddingClient
    from src.rag.mention_query import MentionEvidenceQuery
    from src.storage.repositories import GraphRepository
    from src.storage.repositories.chunk import SimilarChunkRow

__all__ = [
    "AliasLookup",
    "ActiveEntityLookup",
    "Level3NotReadyError",
    "Level3VectorEvidence",
    "DisambigContextProvider",
]


class DisambigContextProvider:
    """证据收集提供器（Provider 层）

    负责收集三级证据并组装为 EvidenceBundle：
    - Level1: 别名表精确映射
    - Level2: 近期活跃实体
    - Level3: 向量语义相似 chunk

    prompt block 的文本渲染已迁移至 renderer 层。
    """

    def __init__(
        self,
        graph_repo: GraphRepository | None = None,
        novel_id: str = "default",
        run_id: str | None = None,
        lookback_chunks: int = 10,
        session: Session | None = None,
        embedding_client: EmbeddingClient | None = None,
        level1_enabled: bool = True,
        level2_enabled: bool = True,
        level3_enabled: bool = True,
        similarity_threshold: float = 0.7,
        level3_top_k: int = 5,
        mention_extractor: PersonMentionExtractor | None = None,
        level3_reranker: Level3ModelReranker | None = None,
        progress_emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
    ) -> None:
        self._alias_lookup = AliasLookup(
            graph_repo=graph_repo,
            run_id=run_id,
        )
        self._active_lookup = ActiveEntityLookup(graph_repo=graph_repo, run_id=run_id)

        self._level3 = Level3VectorEvidence(
            session=session,
            run_id=run_id,
            embedding_client=embedding_client,
            similarity_threshold=similarity_threshold,
            top_k=level3_top_k,
            expected_embedding_dim=settings.models.semantic_chunking.embedding_dim,
        )

        self._graph_repo = graph_repo
        self._run_id = run_id
        self._lookback_chunks = lookback_chunks
        self._authority_snapshot_cache: Level1AuthoritySnapshot | None = None
        self._authority_provider = (
            Level1AuthorityProvider(graph_repo) if graph_repo is not None and run_id is not None else None
        )
        self._graph_authority_service = KnowledgeGraphAuthorityService(graph_repo) if graph_repo is not None else None
        self._level1_enabled = level1_enabled
        self._level2_enabled = level2_enabled
        self._level3_enabled = level3_enabled
        self._level3_top_k = level3_top_k
        self._bundle_builder = EvidenceBundleBuilder()
        self._mention_extraction_service = MentionExtractionService(mention_extractor)
        self._level3_reranker = level3_reranker
        self._progress_emitter = progress_emitter

    async def _emit_level3_progress(self, current_chunk: int | None, message: str, sub_percent: float) -> None:
        """
        创建时间: 2026-04-24
        任务: level3-progress-sse
        说明: 复用现有 stage_progress 事件向前端暴露 Level3/mention 长耗时节点；
              这里只更新 message/sub_stage，不改全局 percent，避免进度条在 chunk 间跳动。
        """
        if self._progress_emitter is None:
            return
        await self._progress_emitter(
            StreamEvent(
                action="progress",
                stage="annotate",
                sub_stage="level3",
                chunk_id=current_chunk,
                sub_percent=sub_percent,
                message=message,
            )
        )

    def set_embedding_client(self, client: EmbeddingClient) -> None:
        """设置 Embedding 客户端"""
        self._level3.set_embedding_client(client)

    def set_session(self, session: Session) -> None:
        """设置数据库会话"""
        if self._run_id:
            self._level3.set_session(session, self._run_id)

    def invalidate_cache(self) -> None:
        """别名映射和关系缓存失效（每个 chunk 处理后调用，因为 projection 可能更新了别名表）"""
        self._alias_lookup.invalidate_cache()
        self._authority_snapshot_cache = None

    def _get_authority_snapshot(self) -> Level1AuthoritySnapshot:
        if not self._level1_enabled or self._authority_provider is None or self._run_id is None:
            return Level1AuthoritySnapshot()
        if self._authority_snapshot_cache is None:
            self._authority_snapshot_cache = self._authority_provider.build_snapshot(self._run_id)
        return self._authority_snapshot_cache

    def _build_structured_evidence(self, names_in_chunk: list[str] | None = None) -> EvidenceBundle:
        snapshot = self._get_authority_snapshot()
        return self._bundle_builder.build_structured_bundle(snapshot, names_in_chunk=names_in_chunk)

    def collect_evidence(
        self,
        names_in_chunk: list[str] | None = None,
        current_chunk: int | None = None,
    ) -> EvidenceBundle:
        """
        收集 Level1/Level2 证据。

        修改时间: 2026-04-23
        任务: fix-coupling-review-findings
        修改内容: authority Level2 合同已落地后，不再吞掉 AttributeError；
                  若 authority 构建异常，直接暴露给调用方，避免静默降级掩盖真实问题。
        """
        bundle = self._build_structured_evidence(names_in_chunk=names_in_chunk)

        if self._level2_enabled and current_chunk is not None:
            candidates = self._active_lookup.get_active_candidates(current_chunk, self._lookback_chunks)
            if self._graph_authority_service is not None and self._run_id is not None:
                active_entities = self._graph_authority_service.build_active_entity_view(
                    self._run_id,
                    current_chunk=current_chunk,
                    lookback=self._lookback_chunks,
                )
            else:
                active_entities = []

            bundle.local_evidence.extend(self._bundle_builder.build_active_entity_items(active_entities))

            if not bundle.local_evidence:
                bundle.local_evidence.extend(self._bundle_builder.build_active_entity_fallback_items(candidates))

        return bundle

    async def collect_evidence_with_level3(self, request: Level3Request) -> EvidenceBundle:
        """
        收集 Level1/2/3 证据。

        修改时间: 2026-04-24
        任务: fix-level3-provider-readiness-drift
        修改说明: 即使 `is_available()` 先前通过，也要在 provider 入口做一次 async readiness 确认；
                  若此时发现 schema/维度漂移，则记录告警并安全降级为无 Level3 证据。

        修改时间: 2026-04-24
        任务: llm-mention-rerank-chain
        修改说明: provider 内部统一执行 mention extraction 与 query 构造，workflow 不再负责 Level3 上游编排。

        修改时间: 2026-04-24
        任务: log-level3-evidence-gaps
        修改说明: 补充 Level3 证据准备入口/出口耗时日志，避免 chunk 间模型取证阶段看起来像空白等待。

        修改时间: 2026-04-25
        任务: level3-intent-phase-split
        修改说明: 旧的弱语义多参数签名已移除，调用方必须显式传入 Level3Request。
        """
        bundle = self.collect_evidence(names_in_chunk=request.seed_entities, current_chunk=request.current_chunk)

        if self._level3_enabled and self.is_level3_available():
            started_at = time.perf_counter()
            logger.info(
                "Level3 evidence collection start: run_id={} objective={} chunk_id={} seed_entities={} "
                "query_len={} max_chunk_id={} top_k={} max_queries={}",
                self._run_id,
                request.objective,
                request.current_chunk,
                len(request.seed_entities),
                len(request.query_text or ""),
                request.max_chunk_id,
                request.top_k,
                request.max_queries,
            )
            await self._emit_level3_progress(
                request.current_chunk,
                f"[{request.objective}] 正在准备 Level3 证据",
                5,
            )
            try:
                await self._level3.ensure_level3_ready()
                plan = await self.build_level3_query_plan(request)
                level3_results = await self.execute_level3_query_plan(
                    plan,
                    request,
                    active_entity_names=self._extract_active_entity_names(bundle),
                    candidate_names=set(bundle.requested_names),
                )
            except Level3NotReadyError as exc:
                # 中文注释：provider 侧必须把 readiness 漂移视为“本次无 Level3 证据”，
                # 不能因为 schema/维度晚于 is_available() 才暴露，就把整条标注链路直接打断。
                logger.warning("Level3 skipped during evidence collection: {}", exc)
                return bundle
            bundle.semantic_evidence.extend(self._bundle_builder.build_semantic_recall_items(level3_results))
            if request.objective == "emotion":
                bundle.semantic_evidence.extend(self._bundle_builder.build_emotion_exemplar_items(level3_results))
            logger.info(
                "Level3 evidence collection complete: run_id={} objective={} chunk_id={} mode={} "
                "mention_queries={} results={} semantic_items={} duration_ms={}",
                self._run_id,
                request.objective,
                request.current_chunk,
                plan.mode,
                len(plan.mention_queries),
                len(level3_results),
                len(bundle.semantic_evidence),
                int((time.perf_counter() - started_at) * 1000),
            )
            await self._emit_level3_progress(
                request.current_chunk,
                f"[{request.objective}] Level3 证据准备完成：召回 {len(level3_results)} 条",
                100,
            )

        return bundle

    async def build_level3_query_plan(self, request: Level3Request) -> Level3QueryPlan:
        """
        创建时间: 2026-04-25
        任务: level3-intent-phase-split
        说明: 按消费者 objective 显式冻结 query planning 规则；高阶 query 只做增量增强，不替代 direct query。
        """
        mention_queries: list[MentionEvidenceQuery] = []
        allow_high_order = request.objective == "identity" and request.allow_llm_query_expansion
        if allow_high_order:
            mention_queries = await self._build_queries(
                context_text=request.query_text,
                seed_entities=request.seed_entities,
                current_chunk=request.current_chunk,
                objective=request.objective,
                max_queries=request.max_queries,
            )

        mode = "hybrid" if mention_queries and request.query_text.strip() else "direct"
        if mention_queries and not request.query_text.strip():
            mode = "high_order"

        return Level3QueryPlan(
            mode=mode,
            base_query_text=request.query_text.strip(),
            mention_queries=mention_queries,
            candidate_pool_k=self._level3_pool_k(request.top_k),
            top_k=request.top_k,
        )

    async def execute_level3_query_plan(
        self,
        plan: Level3QueryPlan,
        request: Level3Request,
        *,
        active_entity_names: set[str],
        candidate_names: set[str],
    ) -> list[SimilarChunkRow]:
        """
        创建时间: 2026-04-25
        任务: level3-intent-phase-split
        说明: 执行显式 query plan；retrieve / rerank / dedupe 仍保留在 provider 编排层，但不再直接耦合 workflow 弱参数。
        """
        return await self._collect_level3_results(
            plan=plan,
            request=request,
            active_entity_names=active_entity_names,
            candidate_names=candidate_names,
        )

    async def _collect_level3_results(
        self,
        *,
        plan: Level3QueryPlan,
        request: Level3Request,
        active_entity_names: set[str],
        candidate_names: set[str],
    ) -> list[SimilarChunkRow]:
        """
        创建时间: 2026-04-25
        任务: level3-intent-phase-split
        说明: query planning 已外提后，这里只负责执行计划、重排候选并按请求预算裁剪。
        """
        started_at = time.perf_counter()
        collected = await self._retrieve_candidates(
            plan=plan,
            request=request,
        )
        retrieved_ms = int((time.perf_counter() - started_at) * 1000)
        logger.info(
            "Level3 candidate retrieval complete: run_id={} objective={} chunk_id={} mode={} "
            "mention_queries={} candidates={} duration_ms={}",
            self._run_id,
            request.objective,
            request.current_chunk,
            plan.mode,
            len(plan.mention_queries),
            len(collected),
            retrieved_ms,
        )
        await self._emit_level3_progress(
            request.current_chunk,
            f"[{request.objective}] Level3 检索完成：候选 {len(collected)} 条",
            60,
        )
        reranked = await self._rerank_candidates(
            collected,
            plan=plan,
            request=request,
            active_entity_names=active_entity_names,
            candidate_names=candidate_names,
        )
        deduped = self._dedupe_level3_results(reranked, top_k=plan.top_k)
        logger.info(
            "Level3 candidate rerank complete: run_id={} objective={} chunk_id={} before_rerank={} "
            "after_rerank={} after_dedupe={} duration_ms={}",
            self._run_id,
            request.objective,
            request.current_chunk,
            len(collected),
            len(reranked),
            len(deduped),
            int((time.perf_counter() - started_at) * 1000),
        )
        await self._emit_level3_progress(
            request.current_chunk,
            f"[{request.objective}] Level3 重排完成：保留 {len(deduped)} 条证据",
            90,
        )
        return deduped

    async def _build_queries(
        self,
        *,
        context_text: str | None,
        seed_entities: list[str],
        current_chunk: int | None,
        objective: str,
        max_queries: int,
    ) -> list[MentionEvidenceQuery]:
        """
        创建时间: 2026-04-25
        任务: level3-intent-phase-split
        说明: 仅 identity objective 允许构造高阶 query，并在 provider 内统一应用 max_queries 预算。
        """
        if not context_text or objective != "identity":
            return []

        from src.rag.mention_query import build_mention_evidence_queries

        started_at = time.perf_counter()
        mentions = await self._extract_mentions(
            context_text=context_text,
            seed_entities=seed_entities,
            current_chunk=current_chunk,
            objective=objective,
        )
        built_queries = build_mention_evidence_queries(mentions)
        if len(built_queries) > max_queries:
            logger.info(
                "Level3 mention queries trimmed by budget: run_id={} chunk_id={} before={} after={}",
                self._run_id,
                current_chunk,
                len(built_queries),
                max_queries,
            )
            built_queries = built_queries[:max_queries]
        logger.info(
            "Level3 mention queries built: run_id={} chunk_id={} mentions={} queries={} duration_ms={}",
            self._run_id,
            current_chunk,
            len(mentions),
            len(built_queries),
            int((time.perf_counter() - started_at) * 1000),
        )
        return built_queries

    async def _extract_mentions(
        self,
        *,
        context_text: str,
        seed_entities: list[str],
        current_chunk: int | None,
        objective: str,
    ) -> list[PersonMention]:
        """
        创建时间: 2026-04-24
        任务: llm-mention-rerank-chain
        说明: 调用 mention extraction service；LLM 失败时由 service 显式 fallback 到规则版。

        修改时间: 2026-04-24
        任务: log-level3-evidence-gaps
        修改说明: 补充 mention extraction 开始/结束耗时日志，直接暴露 chunk 间长等待。
        """
        started_at = time.perf_counter()
        logger.info(
            "Level3 mention extraction start: run_id={} objective={} chunk_id={} text_len={} seed_entities={}",
            self._run_id,
            objective,
            current_chunk,
            len(context_text),
            len(seed_entities),
        )
        await self._emit_level3_progress(current_chunk, f"[{objective}] 正在抽取 Level3 mention", 15)
        mentions = await self._mention_extraction_service.extract_mentions(
            MentionExtractionRequest(
                text=context_text,
                names_in_chunk=tuple(name for name in seed_entities if name),
                context_text=context_text,
                run_id=self._run_id,
                current_chunk=current_chunk,
            )
        )
        logger.info(
            "Level3 mention extraction complete: run_id={} chunk_id={} mentions={} duration_ms={}",
            self._run_id,
            current_chunk,
            len(mentions),
            int((time.perf_counter() - started_at) * 1000),
        )
        await self._emit_level3_progress(
            current_chunk,
            f"[{objective}] Level3 mention 抽取完成：{len(mentions)} 个",
            35,
        )
        return mentions

    async def _retrieve_candidates(
        self,
        *,
        plan: Level3QueryPlan,
        request: Level3Request,
    ) -> list[SimilarChunkRow]:
        """
        创建时间: 2026-04-25
        任务: level3-intent-phase-split
        说明: 按 query plan 执行粗召回；候选池预算统一由 plan.candidate_pool_k 控制。
        """
        collected: list[SimilarChunkRow] = []
        retrieval_top_k = plan.candidate_pool_k
        retrieval_queries = [("mention", mention_query) for mention_query in plan.mention_queries]
        if plan.base_query_text:
            retrieval_queries.append(("base", None))
        if not retrieval_queries:
            return collected

        query_texts = [
            query.query_text if query is not None else plan.base_query_text
            for _, query in retrieval_queries
        ]
        batch_started_at = time.perf_counter()
        results_by_query = await self._search_level3_queries(
            query_texts,
            exclude_chunk_ids=request.exclude_chunk_ids,
            max_chunk_id=request.max_chunk_id,
            top_k=retrieval_top_k,
        )
        logger.debug(
            "Level3 batched retrieval complete: run_id={} objective={} query_count={} duration_ms={}",
            self._run_id,
            request.objective,
            len(query_texts),
            int((time.perf_counter() - batch_started_at) * 1000),
        )
        for index, ((query_kind, mention_query), query_results) in enumerate(
            zip(retrieval_queries, results_by_query, strict=True),
            start=1,
        ):
            if query_kind == "mention" and mention_query is not None:
                logger.debug(
                    "Level3 mention query complete: run_id={} query_index={}/{} query_len={} results={} batched={}",
                    self._run_id,
                    index,
                    len(retrieval_queries),
                    len(mention_query.query_text),
                    len(query_results),
                    len(query_texts) > 1,
                )
                collected.extend(
                    replace(
                        result,
                        query_kind="mention",
                        mention_text=mention_query.mention_text,
                        mention_type=mention_query.mention_type,
                        matched_features=mention_query.matched_features,
                        mention_source=mention_query.mention_source,
                        mention_confidence=mention_query.mention_confidence,
                        query_variant=mention_query.query_variant,
                    )
                    for result in query_results
                )
                continue

            logger.debug(
                "Level3 chunk-context query complete: run_id={} query_len={} results={} batched={}",
                self._run_id,
                len(plan.base_query_text),
                len(query_results),
                len(query_texts) > 1,
            )
            collected.extend(replace(result, query_variant="chunk_context") for result in query_results)

        return collected

    async def _search_level3_queries(
        self,
        query_texts: list[str],
        *,
        exclude_chunk_ids: list[int] | None,
        max_chunk_id: int | None,
        top_k: int | None,
    ) -> list[list[SimilarChunkRow]]:
        """
        创建时间: 2026-04-25
        任务: level3-intent-phase-split
        说明: 多 query 时统一走 batched Level3 检索，单 query 仍复用既有入口，
              避免热路径继续逐条请求 embedding 服务。
        """
        if not query_texts:
            return []
        if len(query_texts) == 1:
            single_result = await self._search_level3_query(
                query_texts[0],
                exclude_chunk_ids=exclude_chunk_ids,
                max_chunk_id=max_chunk_id,
                top_k=top_k,
            )
            return [single_result]
        return await self._level3.search_similar_chunks_many(
            query_texts,
            exclude_chunk_ids=exclude_chunk_ids,
            max_chunk_id=max_chunk_id,
            top_k=top_k,
            ensure_ready=False,
        )

    async def _rerank_candidates(
        self,
        results: list[SimilarChunkRow],
        *,
        plan: Level3QueryPlan,
        request: Level3Request,
        active_entity_names: set[str],
        candidate_names: set[str],
    ) -> list[SimilarChunkRow]:
        """
        创建时间: 2026-04-25
        任务: level3-intent-phase-split
        说明: plan 决定是否存在高阶 query；只有 hybrid/high_order 情况才启用 deterministic mention rerank。
        """
        collected = results
        if plan.mention_queries:
            collected = rerank_mention_level3_results(
                collected,
                active_entity_names=active_entity_names,
                candidate_names=candidate_names,
                current_chunk=request.current_chunk,
            )

        model_query_text = self._build_model_rerank_query_text(plan)
        logger.info(
            "Level3 model rerank start: run_id={} objective={} chunk_id={} candidates={} query_len={} model_enabled={}",
            self._run_id,
            request.objective,
            request.current_chunk,
            len(collected),
            len(model_query_text),
            self._level3_reranker is not None,
        )
        if self._level3_reranker is not None and collected:
            await self._emit_level3_progress(
                request.current_chunk,
                f"[{request.objective}] 正在执行 Level3 模型重排",
                75,
            )
        model_reranked = await try_model_rerank_level3_results(
            collected[: plan.candidate_pool_k],
            query_text=model_query_text,
            reranker=self._level3_reranker,
            run_id=self._run_id,
            chunk_id=request.current_chunk,
        )
        if model_reranked is not None:
            logger.info(
                "Level3 model rerank applied: run_id={} objective={} chunk_id={} candidates={}",
                self._run_id,
                request.objective,
                request.current_chunk,
                len(model_reranked),
            )
            return model_reranked
        logger.info(
            "Level3 model rerank skipped or unavailable: run_id={} objective={} chunk_id={} candidates={}",
            self._run_id,
            request.objective,
            request.current_chunk,
            len(collected),
        )
        return collected

    def _build_model_rerank_query_text(self, plan: Level3QueryPlan) -> str:
        """
        创建时间: 2026-04-24
        任务: llm-mention-rerank-chain
        说明: 给模型 rerank 汇总原文 query 与 mention query，避免模型只看到压缩词而丢失当前语境。
        """
        parts = [plan.base_query_text] if plan.base_query_text else []
        for query in plan.mention_queries:
            if query.query_text not in parts:
                parts.append(query.query_text)
        return "\n".join(parts)

    async def _search_level3_query(
        self,
        query_text: str,
        *,
        exclude_chunk_ids: list[int] | None,
        max_chunk_id: int | None,
        top_k: int | None,
    ) -> list[SimilarChunkRow]:
        """
        创建时间: 2026-04-24
        任务: level3-mention-rerank
        说明: 包装 Level3 query 调用；仅在 mention retrieval 需要扩大召回池时传入 top_k。
        """
        if top_k is None:
            return await self._level3.search_similar_chunks(
                query_text,
                exclude_chunk_ids=exclude_chunk_ids,
                max_chunk_id=max_chunk_id,
                ensure_ready=False,
            )
        return await self._level3.search_similar_chunks(
            query_text,
            exclude_chunk_ids=exclude_chunk_ids,
            max_chunk_id=max_chunk_id,
            top_k=top_k,
            ensure_ready=False,
        )

    def _dedupe_level3_results(self, results: list[SimilarChunkRow], *, top_k: int) -> list[SimilarChunkRow]:
        """
        创建时间: 2026-04-23
        任务: level3-mention-retrieval
        说明: 对多 query 的 Level3 结果按 chunk_id 去重；同分时优先保留 mention 来源，方便后续观察。

        修改时间: 2026-04-24
        任务: level3-mention-rerank
        修改说明: 若存在 business / final 排序分，则按新分数字段去重和排序；否则保持原 similarity 语义。
        """
        by_chunk_id: dict[int, SimilarChunkRow] = {}
        for result in results:
            existing = by_chunk_id.get(result.chunk_id)
            if existing is None:
                by_chunk_id[result.chunk_id] = result
                continue
            if self._level3_rank_score(result) > self._level3_rank_score(existing):
                by_chunk_id[result.chunk_id] = result
            elif (
                self._level3_rank_score(result) == self._level3_rank_score(existing)
                and existing.query_kind != "mention"
            ):
                by_chunk_id[result.chunk_id] = result

        ordered = sorted(by_chunk_id.values(), key=self._level3_rank_score, reverse=True)
        return ordered[:top_k]

    def _level3_rank_score(self, result: SimilarChunkRow) -> float:
        """
        创建时间: 2026-04-24
        任务: level3-mention-rerank
        说明: 统一读取 Level3 排序分，确保 rerank 与旧 similarity 排序路径共用同一比较逻辑。

        修改时间: 2026-04-24
        任务: split-level3-score-fields
        修改说明: 优先读取显式 final/business/paragraph/chunk 分数，避免后续模型 rerank 接入时继续依赖歧义字段。
        """
        if result.final_rank_score is not None:
            return result.final_rank_score
        if result.business_rerank_score is not None:
            return result.business_rerank_score
        if result.paragraph_semantic_score is not None:
            return result.paragraph_semantic_score
        if result.chunk_semantic_score is not None:
            return result.chunk_semantic_score
        return result.similarity

    def _level3_pool_k(self, top_k: int) -> int:
        """
        创建时间: 2026-04-25
        任务: level3-intent-phase-split
        说明: Level3 候选池预算不再由各路径各自推断，而是统一从 final top_k 派生。
        """
        return max(top_k * 4, 20)

    def _extract_active_entity_names(self, bundle: EvidenceBundle) -> set[str]:
        """
        创建时间: 2026-04-24
        任务: level3-mention-rerank
        说明: 从 Level2 evidence 中提取活跃实体名，作为 rerank 加权输入，不额外查询数据库。
        """
        names: set[str] = set()
        for item in bundle.local_evidence:
            if item.evidence_type != "active_entity":
                continue
            metadata_name = item.metadata.get("name")
            name = str(metadata_name or item.content).strip()
            if name:
                names.add(name)
        return names

    def is_level3_available(self) -> bool:
        """检查 Level 3 是否可用"""
        return self._level3_enabled and self._level3.is_available()

    def requires_level3(self) -> bool:
        """检查当前 provider 是否按当前流程配置要求启用 Level 3。"""
        return self._level3_enabled

    async def ensure_level3_ready(self) -> None:
        if self._level3_enabled:
            await self._level3.ensure_level3_ready()
