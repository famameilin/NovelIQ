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

修改时间: 2026-04-25
修改者: Codex
任务: evidence-service-request-unification
修改内容: 将公开语义从 DisambigContextProvider 收口到 NarrativeEvidenceService.collect(request)，
    workflow 不再决定走哪个 evidence 入口，EvidenceRequest 也同步升格为统一输入合同。

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
from typing import TYPE_CHECKING, Any

from loguru import logger

from src.api.models.events import StreamEvent
from src.config import settings
from src.knowledge.authority import KnowledgeGraphAuthorityService
from src.rag.authority import Level1AuthorityProvider
from src.rag.evidence_bundle_builder import EvidenceBundleBuilder
from src.rag.evidence_contracts import (
    EvidenceRequest,
    Level3QueryMode,
    Level3QueryPlan,
    build_evidence_request_fingerprint,
)
from src.rag.evidence_types import EvidenceBundle, Level1AuthoritySnapshot
from src.rag.level1_alias import AliasLookup
from src.rag.level2_active_entities import ActiveEntityLookup
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
    "NarrativeEvidenceService",
]


def _merge_annotation_phase1_identity_and_emotion_bundles(
    identity_bundle: EvidenceBundle,
    emotion_bundle: EvidenceBundle,
) -> EvidenceBundle:
    """
    创建时间: 2026-04-25
    任务: evidence-service-request-unification
    说明: Phase1 需要 identity semantic recall + emotion exemplar；
          overlay 合并在 service 内完成，workflow 不再自己拼两份 bundle。
    """
    merged_semantic_evidence = list(identity_bundle.semantic_evidence)
    existing_emotion_keys = {
        (item.evidence_type, item.chunk_id, item.content)
        for item in merged_semantic_evidence
        if item.evidence_type == "emotion_exemplar"
    }
    for item in emotion_bundle.semantic_evidence:
        if item.evidence_type != "emotion_exemplar":
            continue
        dedupe_key = (item.evidence_type, item.chunk_id, item.content)
        if dedupe_key in existing_emotion_keys:
            continue
        merged_semantic_evidence.append(item)
        existing_emotion_keys.add(dedupe_key)

    return EvidenceBundle(
        structured_evidence=list(identity_bundle.structured_evidence),
        local_evidence=list(identity_bundle.local_evidence),
        semantic_evidence=merged_semantic_evidence,
        requested_names=list(identity_bundle.requested_names),
        level1_snapshot=identity_bundle.level1_snapshot,
        request_meta=dict(identity_bundle.request_meta),
        generation_meta={
            **identity_bundle.generation_meta,
            "emotion_overlay_applied": True,
        },
    )


def _should_apply_annotation_phase1_overlay(request: EvidenceRequest) -> bool:
    """
    创建时间: 2026-04-25
    任务: evidence-service-request-unification
    说明: Phase1 的 identity request 对外仍只暴露单一 EvidenceRequest；
          若需要 emotion exemplar overlay，由 service 在 collect() 内部统一补齐。
    """
    return request.consumer == "annotation_phase1" and request.objective == "identity" and request.need_level3


class NarrativeEvidenceService:
    """叙事证据服务（Evidence Service 层）

    负责接收统一的 EvidenceRequest，并编排三级证据为 EvidenceBundle：
    - Level1: 别名表精确映射
    - Level2: 近期活跃实体
    - Level3: 向量语义相似 chunk

    prompt block 的文本渲染仍留在 renderer 层；service 只负责取证编排。
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
        self._bundle_cache: dict[tuple[object, ...], EvidenceBundle] = {}

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
        self._bundle_cache.clear()

    def _get_authority_snapshot(self) -> Level1AuthoritySnapshot:
        if not self._level1_enabled or self._authority_provider is None or self._run_id is None:
            return Level1AuthoritySnapshot()
        if self._authority_snapshot_cache is None:
            self._authority_snapshot_cache = self._authority_provider.build_snapshot(self._run_id)
        return self._authority_snapshot_cache

    def _build_structured_evidence(self, requested_names: list[str] | None = None) -> EvidenceBundle:
        """
        创建时间: 2026-04-25
        任务: evidence-service-request-unification
        说明: Level1 只按 request.requested_names 过滤；
              不再把 retrieval seed_entities 误当成“当前 consumer 真正要看的名字”。
        """
        snapshot = self._get_authority_snapshot()
        return self._bundle_builder.build_structured_bundle(snapshot, requested_names=requested_names)

    def _build_request_meta(self, request: EvidenceRequest) -> dict[str, Any]:
        """
        创建时间: 2026-04-25
        任务: evidence-service-request-unification
        说明: request_meta 直接记录调用方显式声明的输入边界，方便后续日志、回放和问题归因。
        """
        return {
            "consumer": request.consumer,
            "objective": request.objective,
            "requested_names": list(request.requested_names),
            "seed_entities": list(request.seed_entities),
            "background_entities": list(request.background_entities),
            "current_chunk": request.current_chunk,
            "max_chunk_id": request.max_chunk_id,
            "exclude_chunk_ids": list(request.exclude_chunk_ids),
        }

    def _build_generation_meta(self, request: EvidenceRequest) -> dict[str, Any]:
        """
        创建时间: 2026-04-25
        任务: evidence-service-request-unification
        说明: generation_meta 统一承载本次 evidence 编排观察字段；
              即使某条路径没有真正执行 Level3，也保留稳定键名，避免观察面继续分裂。
        """
        return {
            "need_level1": request.need_level1,
            "need_level2": request.need_level2,
            "need_level3": request.need_level3,
            "level3_executed": False,
            "query_mode": "disabled",
            "query_count": 0,
            "top_k": request.top_k,
            "failed_queries": [],
            "dropped_queries": [],
            "batch_mode": "none",
            "cache_reuse": False,
            "level3_skipped_reason": None,
            "empty_query_fallback_reason": None,
        }

    def _restore_cached_bundle(self, request: EvidenceRequest) -> EvidenceBundle | None:
        """
        创建时间: 2026-04-25
        任务: evidence-service-request-unification
        说明: cache 只复用 evidence 内容本身；每次命中后仍用当前 request 的 meta 重新打戳，
              避免 Phase1/Phase3 这类 consumer 复用时把上一跳标签带过去。
        """
        cache_key = build_evidence_request_fingerprint(request)
        cached_bundle = self._bundle_cache.get(cache_key)
        if cached_bundle is None:
            return None
        generation_meta = dict(cached_bundle.generation_meta)
        generation_meta["cache_reuse"] = True
        return cached_bundle.clone_with_meta(
            request_meta=self._build_request_meta(request),
            generation_meta=generation_meta,
        )

    def _cache_bundle(self, request: EvidenceRequest, bundle: EvidenceBundle) -> None:
        """
        创建时间: 2026-04-25
        任务: evidence-service-request-unification
        说明: service 级 cache 只按真实取证语义复用，供同一 chunk 内的多 consumer 复用相同 bundle。
        """
        cache_key = build_evidence_request_fingerprint(request)
        self._bundle_cache[cache_key] = bundle.clone_with_meta()

    def _collect_base_evidence(self, request: EvidenceRequest) -> EvidenceBundle:
        """
        收集 Level1/Level2 证据。

        修改时间: 2026-04-23
        任务: fix-coupling-review-findings
        修改内容: authority Level2 合同已落地后，不再吞掉 AttributeError；
                  若 authority 构建异常，直接暴露给调用方，避免静默降级掩盖真实问题。

        修改时间: 2026-04-25
        任务: evidence-service-request-unification
        修改内容: base evidence 改由统一 request 驱动；
                  Level1 只消费 requested_names，Level2 只受 need_level2/current_chunk 控制。
        """
        if request.need_level1:
            bundle = self._build_structured_evidence(requested_names=request.requested_names)
        else:
            bundle = EvidenceBundle(
                structured_evidence=[],
                requested_names=list(request.requested_names),
                level1_snapshot=None,
            )

        if request.need_level2 and self._level2_enabled and request.current_chunk is not None:
            candidates = self._active_lookup.get_active_candidates(request.current_chunk, self._lookback_chunks)
            if self._graph_authority_service is not None and self._run_id is not None:
                active_entities = self._graph_authority_service.build_active_entity_view(
                    self._run_id,
                    current_chunk=request.current_chunk,
                    lookback=self._lookback_chunks,
                )
            else:
                active_entities = []

            bundle.local_evidence.extend(self._bundle_builder.build_active_entity_items(active_entities))

            if not bundle.local_evidence:
                bundle.local_evidence.extend(self._bundle_builder.build_active_entity_fallback_items(candidates))

        bundle.requested_names = list(request.requested_names)
        return bundle

    def _build_annotation_phase1_emotion_request(self, request: EvidenceRequest) -> EvidenceRequest:
        """
        创建时间: 2026-04-25
        任务: evidence-service-request-unification
        说明: Phase1 对外只暴露 identity request；
              emotion overlay 的 query 由 service 内部派生，避免 workflow 再显式管理第二份 request。
        """
        return replace(
            request,
            objective="emotion",
            seed_entities=[],
            need_level1=False,
            need_level2=False,
            allow_llm_query_expansion=False,
        )

    def _build_annotation_phase1_identity_base_request(self, request: EvidenceRequest) -> EvidenceRequest:
        """
        创建时间: 2026-04-26
        任务: fix-phase1-phase3-base-cache-reuse
        说明: Phase1 的 emotion overlay 只改变最终返回 bundle，不改变 identity base recall；
              这里显式派生一个“无 overlay content variant”的请求键，供 Phase3 等纯 identity consumer
              复用同一份 Level3 base evidence，避免同 chunk 重复 embedding/检索/rerank。
        """
        return replace(request, consumer="annotation_phase3")

    async def _collect_request(
        self,
        request: EvidenceRequest,
        *,
        allow_cache: bool,
        store_cache: bool,
    ) -> EvidenceBundle:
        """
        创建时间: 2026-04-25
        任务: evidence-service-request-unification
        说明: 统一执行单条 EvidenceRequest，不处理 annotation Phase1 的 overlay 特例；
              collect() 会在需要时用这个基础执行器拼出最终返回值。
        """
        if allow_cache:
            cached_bundle = self._restore_cached_bundle(request)
            if cached_bundle is not None:
                return cached_bundle

        bundle = self._collect_base_evidence(request)
        bundle.request_meta = self._build_request_meta(request)
        bundle.generation_meta = self._build_generation_meta(request)

        if not request.need_level3:
            if store_cache:
                self._cache_bundle(request, bundle)
            return bundle

        if not request.query_text:
            bundle.generation_meta["level3_skipped_reason"] = "query_text_empty"
            bundle.generation_meta["empty_query_fallback_reason"] = "query_text_empty"
            if store_cache:
                self._cache_bundle(request, bundle)
            return bundle

        if not self.is_level3_available():
            if self.requires_level3():
                raise RuntimeError("Level 3 vector retrieval is required but not available")
            bundle.generation_meta["level3_skipped_reason"] = "level3_unavailable"
            if store_cache:
                self._cache_bundle(request, bundle)
            return bundle

        started_at = time.perf_counter()
        logger.info(
            "Level3 evidence collection start: run_id={} consumer={} objective={} chunk_id={} "
            "requested_names={} seed_entities={} query_len={} max_chunk_id={} top_k={} max_queries={}",
            self._run_id,
            request.consumer,
            request.objective,
            request.current_chunk,
            len(request.requested_names),
            len(request.seed_entities),
            len(request.query_text),
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
            level3_results, failed_queries = await self.execute_level3_query_plan(
                plan,
                request,
                active_entity_names=self._extract_active_entity_names(bundle),
                candidate_names=set(request.requested_names),
            )
        except Level3NotReadyError as exc:
            if self.requires_level3():
                # 中文注释：required Level3 语义下，入口已声明“没有 Level3 就不能继续”，
                # 因此 async readiness 漂移必须 fail loudly，不能偷偷退回 Level1/2。
                logger.error("Level3 readiness drift surfaced on required path: {}", exc)
                raise
            logger.warning("Level3 skipped during evidence collection: {}", exc)
            bundle.generation_meta["level3_skipped_reason"] = "readiness_failed"
            if store_cache:
                self._cache_bundle(request, bundle)
            return bundle

        bundle.semantic_evidence.extend(self._bundle_builder.build_semantic_recall_items(level3_results))
        if request.objective == "emotion":
            bundle.semantic_evidence.extend(self._bundle_builder.build_emotion_exemplar_items(level3_results))

        query_count = len(plan.mention_queries) + (1 if plan.base_query_text else 0)
        bundle.generation_meta.update(
            {
                "level3_executed": True,
                "query_mode": plan.mode,
                "query_count": query_count,
                "top_k": plan.top_k,
                "batch_mode": "batched" if query_count > 1 else "single",
                "failed_queries": failed_queries,
                "dropped_queries": list(plan.dropped_queries),
            }
        )
        logger.info(
            "Level3 evidence collection complete: run_id={} consumer={} objective={} chunk_id={} mode={} "
            "mention_queries={} results={} semantic_items={} duration_ms={}",
            self._run_id,
            request.consumer,
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

        if store_cache:
            self._cache_bundle(request, bundle)
        return bundle

    async def collect(self, request: EvidenceRequest) -> EvidenceBundle:
        """
        收集统一 evidence bundle。

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
        任务: evidence-service-request-unification
        修改说明: 对外公开入口收口为 collect(request)；
                  workflow 不再决定走 Level1/2 还是 Level1/2/3，而是统一由 service 按 request.need_level* 编排。
        """
        if not _should_apply_annotation_phase1_overlay(request):
            return await self._collect_request(request, allow_cache=True, store_cache=True)

        cached_bundle = self._restore_cached_bundle(request)
        if cached_bundle is not None:
            return cached_bundle

        base_request = self._build_annotation_phase1_identity_base_request(request)
        identity_bundle = self._restore_cached_bundle(base_request)
        if identity_bundle is None:
            identity_bundle = await self._collect_request(request, allow_cache=False, store_cache=False)
            # 中文注释：先把不带 emotion overlay 的 identity base 存进“普通 identity”缓存键，
            # 后续 annotation_phase3 命中同语义请求时即可直接复用，不必再跑一轮 Level3 热路径。
            self._cache_bundle(base_request, identity_bundle)
        if not identity_bundle.generation_meta.get("level3_executed"):
            self._cache_bundle(request, identity_bundle)
            return identity_bundle

        emotion_request = self._build_annotation_phase1_emotion_request(request)
        emotion_bundle = await self._collect_request(emotion_request, allow_cache=True, store_cache=True)
        merged_bundle = _merge_annotation_phase1_identity_and_emotion_bundles(identity_bundle, emotion_bundle)
        self._cache_bundle(request, merged_bundle)
        return merged_bundle

    async def build_level3_query_plan(self, request: EvidenceRequest) -> Level3QueryPlan:
        """
        创建时间: 2026-04-25
        任务: level3-intent-phase-split
        说明: 按消费者 objective 显式冻结 query planning 规则；高阶 query 只做增量增强，不替代 direct query。

        修改时间: 2026-04-25
        任务: fix-level3-typecheck-regressions
        修改说明: 显式收紧 `mode` 的 Literal 类型，避免 request->plan 改造后破坏仓库 typecheck。
        """
        mention_queries: list[MentionEvidenceQuery] = []
        dropped_queries: list[dict[str, str]] = []
        allow_high_order = request.allow_llm_query_expansion and request.objective in {"identity", "relation"}
        if allow_high_order:
            mention_queries, dropped_queries = await self._build_queries(
                context_text=request.query_text,
                seed_entities=request.seed_entities,
                current_chunk=request.current_chunk,
                objective=request.objective,
                max_queries=request.max_queries,
            )

        base_query_text = request.query_text.strip()
        mode: Level3QueryMode = "direct"
        if mention_queries:
            mode = "hybrid" if base_query_text else "high_order"

        return Level3QueryPlan(
            mode=mode,
            base_query_text=base_query_text,
            mention_queries=mention_queries,
            candidate_pool_k=self._level3_pool_k(request.top_k),
            top_k=request.top_k,
            dropped_queries=dropped_queries,
        )

    async def execute_level3_query_plan(
        self,
        plan: Level3QueryPlan,
        request: EvidenceRequest,
        *,
        active_entity_names: set[str],
        candidate_names: set[str],
    ) -> tuple[list[SimilarChunkRow], list[dict[str, object]]]:
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
        request: EvidenceRequest,
        active_entity_names: set[str],
        candidate_names: set[str],
    ) -> tuple[list[SimilarChunkRow], list[dict[str, object]]]:
        """
        创建时间: 2026-04-25
        任务: level3-intent-phase-split
        说明: query planning 已外提后，这里只负责执行计划、重排候选并按请求预算裁剪。
        """
        started_at = time.perf_counter()
        collected, failed_queries = await self._retrieve_candidates(
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
        return deduped, failed_queries

    async def _build_queries(
        self,
        *,
        context_text: str | None,
        seed_entities: list[str],
        current_chunk: int | None,
        objective: str,
        max_queries: int,
    ) -> tuple[list[MentionEvidenceQuery], list[dict[str, str]]]:
        """
        创建时间: 2026-04-25
        任务: level3-intent-phase-split
        说明: 按 objective 构造高阶 query；identity 默认允许完整 hybrid，
              relation 仅在显式允许时做受限扩展，其余目标保持 direct-only。
        """
        if not context_text or objective not in {"identity", "relation"}:
            return [], []

        from src.rag.mention_query import build_mention_evidence_queries

        started_at = time.perf_counter()
        mentions = await self._extract_mentions(
            context_text=context_text,
            seed_entities=seed_entities,
            current_chunk=current_chunk,
            objective=objective,
        )
        built_queries = build_mention_evidence_queries(mentions)
        dropped_queries: list[dict[str, str]] = []
        effective_max_queries = max_queries if objective == "identity" else min(max_queries, 2)
        if len(built_queries) > effective_max_queries:
            dropped_queries = [
                {
                    "query_text": query.query_text,
                    "mention_text": query.mention_text,
                    "query_variant": query.query_variant,
                    "reason": "max_queries_budget",
                }
                for query in built_queries[effective_max_queries:]
            ]
            logger.info(
                "Level3 mention queries trimmed by budget: run_id={} chunk_id={} before={} after={}",
                self._run_id,
                current_chunk,
                len(built_queries),
                effective_max_queries,
            )
            built_queries = built_queries[:effective_max_queries]
        logger.info(
            "Level3 mention queries built: run_id={} chunk_id={} mentions={} queries={} duration_ms={}",
            self._run_id,
            current_chunk,
            len(mentions),
            len(built_queries),
            int((time.perf_counter() - started_at) * 1000),
        )
        return built_queries, dropped_queries

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

        修改时间: 2026-04-25
        任务: fix-level3-relation-query-expansion-contract
        修改内容: identity 才允许走 LLM 主路径；relation 的受限扩展只复用规则 extractor，
                  避免 Phase4 类消费者一旦显式放开 expansion 就被统一拉进高成本 LLM 热路径。
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
            ),
            prefer_llm=objective == "identity",
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
        request: EvidenceRequest,
    ) -> tuple[list[SimilarChunkRow], list[dict[str, object]]]:
        """
        创建时间: 2026-04-25
        任务: level3-intent-phase-split
        说明: 按 query plan 执行粗召回；候选池预算统一由 plan.candidate_pool_k 控制。

        修改时间: 2026-04-25
        任务: fix-level3-typecheck-regressions
        修改说明: 显式声明 mixed base/mention query 元组类型，避免 tuple 推断过窄影响仓库 typecheck。
        """
        collected: list[SimilarChunkRow] = []
        failed_queries: list[dict[str, object]] = []
        retrieval_top_k = plan.candidate_pool_k
        retrieval_queries: list[tuple[str, MentionEvidenceQuery | None]] = [
            ("mention", mention_query) for mention_query in plan.mention_queries
        ]
        if plan.base_query_text:
            retrieval_queries.append(("base", None))
        if not retrieval_queries:
            return collected, failed_queries

        query_texts = [
            query.query_text if query is not None else plan.base_query_text
            for _, query in retrieval_queries
        ]
        batch_started_at = time.perf_counter()
        results_by_query, level3_failures = await self._search_level3_queries(
            query_texts,
            exclude_chunk_ids=request.exclude_chunk_ids,
            max_chunk_id=request.max_chunk_id,
            top_k=retrieval_top_k,
        )
        failure_by_index: dict[int, dict[str, object]] = {}
        for failure in level3_failures:
            query_index = failure.get("query_index")
            if isinstance(query_index, int):
                failure_by_index[query_index] = failure
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
            query_failure: dict[str, object] | None = failure_by_index.get(index - 1)
            if query_failure is not None:
                failure_entry: dict[str, object] = {
                    "query_index": index - 1,
                    "query_kind": query_kind,
                    "query_text": query_failure.get("query_text"),
                    "stage": query_failure.get("stage"),
                    "reason": query_failure.get("reason"),
                }
                if mention_query is not None:
                    failure_entry.update(
                        {
                            "mention_text": mention_query.mention_text,
                            "query_variant": mention_query.query_variant,
                        }
                    )
                failed_queries.append(failure_entry)
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

        return collected, failed_queries

    async def _search_level3_queries(
        self,
        query_texts: list[str],
        *,
        exclude_chunk_ids: list[int] | None,
        max_chunk_id: int | None,
        top_k: int | None,
    ) -> tuple[list[list[SimilarChunkRow]], list[dict[str, object]]]:
        """
        创建时间: 2026-04-25
        任务: level3-intent-phase-split
        说明: 多 query 时统一走 batched Level3 检索，单 query 仍复用既有入口，
              避免热路径继续逐条请求 embedding 服务。
        """
        if not query_texts:
            return [], []
        if len(query_texts) == 1:
            single_result = await self._search_level3_query(
                query_texts[0],
                exclude_chunk_ids=exclude_chunk_ids,
                max_chunk_id=max_chunk_id,
                top_k=top_k,
            )
            failures = self._level3.consume_last_query_failures()
            for failure in failures:
                failure.setdefault("query_index", 0)
            return [single_result], failures
        results_by_query = await self._level3.search_similar_chunks_many(
            query_texts,
            exclude_chunk_ids=exclude_chunk_ids,
            max_chunk_id=max_chunk_id,
            top_k=top_k,
            ensure_ready=False,
        )
        return results_by_query, self._level3.consume_last_query_failures()

    async def _rerank_candidates(
        self,
        results: list[SimilarChunkRow],
        *,
        plan: Level3QueryPlan,
        request: EvidenceRequest,
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

        model_query_text = self._build_model_rerank_query_text(plan, request)
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

    def _build_model_rerank_query_text(self, plan: Level3QueryPlan, request: EvidenceRequest) -> str:
        """
        创建时间: 2026-04-24
        任务: llm-mention-rerank-chain
        说明: 给模型 rerank 汇总原文 query 与 mention query，避免模型只看到压缩词而丢失当前语境。

        修改时间: 2026-04-25
        任务: fix-level3-required-readiness-and-rerank-budget
        修改说明: rerank 不再直接拼接无限增长的原文 query；这里会优先选取压缩 query 变体，
                  并严格按 request.model_rerank_query_max_chars 收口总长度。
        """
        max_chars = max(int(request.model_rerank_query_max_chars), 0)
        if max_chars <= 0:
            return ""

        segments = self._collect_model_rerank_query_segments(plan)
        return self._render_model_rerank_query_segments(segments, max_chars=max_chars)

    def _collect_model_rerank_query_segments(self, plan: Level3QueryPlan) -> list[tuple[str, str]]:
        """
        创建时间: 2026-04-25
        任务: fix-level3-required-readiness-and-rerank-budget
        说明: 为 model rerank 组装 query summary 片段；base query 保留语境，
              mention query 则优先选更短、更稳定的压缩/特征变体，避免重复拼入整段原文。
        """
        segments: list[tuple[str, str]] = []
        base_query_text = " ".join(plan.base_query_text.split())
        if base_query_text:
            segments.append(("base", base_query_text))

        variant_priority = {
            "mention_compressed": 0,
            "mention_feature": 1,
            "mention_raw": 2,
        }
        best_query_by_mention: dict[str, MentionEvidenceQuery] = {}
        for query in plan.mention_queries:
            mention_key = query.mention_text.strip() or query.query_text.strip()
            existing = best_query_by_mention.get(mention_key)
            if existing is None:
                best_query_by_mention[mention_key] = query
                continue
            current_priority = variant_priority.get(existing.query_variant, 99)
            next_priority = variant_priority.get(query.query_variant, 99)
            if next_priority < current_priority:
                best_query_by_mention[mention_key] = query
                continue
            if next_priority == current_priority and len(query.query_text) < len(existing.query_text):
                best_query_by_mention[mention_key] = query

        for mention_index, query in enumerate(best_query_by_mention.values(), start=1):
            compact_query_text = " ".join(query.query_text.split())
            if compact_query_text:
                segments.append((f"q{mention_index}", compact_query_text))
        return segments

    def _render_model_rerank_query_segments(self, segments: list[tuple[str, str]], *, max_chars: int) -> str:
        """
        创建时间: 2026-04-25
        任务: fix-level3-required-readiness-and-rerank-budget
        说明: 将 summary 片段压缩到固定字符预算内；这里按“每段至少保留最小摘要”的方式分配，
              避免 base query 吞掉全部 budget，或后续 mention summary 完全挤不进去。
        """
        if max_chars <= 0:
            return ""

        rendered_parts: list[str] = []
        remaining = max_chars
        minimum_body_chars = 12

        for index, (label, text) in enumerate(segments):
            cleaned_text = " ".join(text.split())
            if not cleaned_text:
                continue
            separator = "\n" if rendered_parts else ""
            remaining_segment_count = len(segments) - index
            available_for_current = max(remaining - len(separator), 0)
            if available_for_current <= len(label) + 2:
                break

            target_segment_budget = max(
                available_for_current // remaining_segment_count,
                len(label) + 2 + minimum_body_chars,
            )
            body_budget = min(
                max(target_segment_budget - len(label) - 2, minimum_body_chars),
                available_for_current - len(label) - 2,
            )
            summarized_text = self._summarize_model_rerank_query_text(cleaned_text, max_chars=body_budget)
            if not summarized_text:
                continue

            candidate = f"{label}: {summarized_text}"
            if len(separator) + len(candidate) > remaining:
                overflow_budget = remaining - len(separator) - len(label) - 2
                if overflow_budget <= 0:
                    break
                summarized_text = self._summarize_model_rerank_query_text(cleaned_text, max_chars=overflow_budget)
                if not summarized_text:
                    break
                candidate = f"{label}: {summarized_text}"

            rendered_parts.append(candidate)
            remaining -= len(separator) + len(candidate)
            if remaining <= 0:
                break

        return "\n".join(rendered_parts)

    def _summarize_model_rerank_query_text(self, text: str, *, max_chars: int) -> str:
        """
        创建时间: 2026-04-25
        任务: fix-level3-required-readiness-and-rerank-budget
        说明: 对单条 rerank query 片段做最小压缩；优先保留前缀关键信息，超长时用省略号截断。
        """
        cleaned_text = " ".join(text.split())
        if max_chars <= 0 or not cleaned_text:
            return ""
        if len(cleaned_text) <= max_chars:
            return cleaned_text
        if max_chars <= 3:
            return cleaned_text[:max_chars]
        return f"{cleaned_text[: max_chars - 3]}..."

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
