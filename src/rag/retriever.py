"""
说明: 本模块提供证据收集功能（Provider 层），支持三级证据：
- Level1: 别名表精确匹配
- Level2: 活跃实体候选
- Level3: 向量语义相似度检索
输出统一 EvidenceBundle，由下游 renderer 渲染为 prompt 内容
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
    Level3QueryPlan,
    build_evidence_request_fingerprint,
)
from src.rag.evidence_types import EvidenceBundle, Level1AuthoritySnapshot
from src.rag.level1_alias import AliasLookup
from src.rag.level2_active_entities import ActiveEntityLookup
from src.rag.level3_vector import Level3NotReadyError, Level3VectorEvidence
from src.rag.mention_extraction_types import MentionExtractionRequest, PersonMention
from src.rag.mention_rerank import rerank_mention_level3_results
from src.rag.model_rerank import Level3ModelReranker, try_model_rerank_level3_results
from src.rag.query_example_planner import (
    build_query_examples_from_mentions,
    build_rule_query_examples,
    collect_descriptive_anchor_texts,
)
from src.rag.query_example_types import (
    Level3ExpansionQuery,
    Level3QueryExamplePlanner,
    QueryExamplePlannerRequest,
    QueryExamplePlannerResult,
    QueryPlannerKind,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.models.local.embedding import EmbeddingClient
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
    说明: Phase1 需要 identity semantic recall + emotion exemplar；
          overlay 合并在 service 内完成，workflow 不再自己拼两份 bundle
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
        reference_slots=list(identity_bundle.reference_slots),
        level1_snapshot=identity_bundle.level1_snapshot,
        request_meta=dict(identity_bundle.request_meta),
        generation_meta={
            **identity_bundle.generation_meta,
            "emotion_overlay_applied": True,
        },
    )


def _should_apply_annotation_phase1_overlay(request: EvidenceRequest) -> bool:
    """
    说明: Phase1 的 identity request 对外仍只暴露单一 EvidenceRequest；
          若需要 emotion exemplar overlay，由 service 在 collect() 内部统一补齐
    """
    return request.consumer == "annotation_phase1" and request.objective == "identity" and request.need_level3


class _LegacyMentionExtractorQueryPlannerAdapter:
    """
    创建时间: 2026-04-30
    任务: level3-query-exampler-mainline
    说明: 在 workflow 仍通过旧 `mention_extractor` alias 注入 LLM transport 时，
          将旧的 `extract_mentions()` 能力桥接成新的 `plan_queries()` 协议，避免主链切换期间 runtime 失配。
    """

    def __init__(self, legacy_extractor: Any) -> None:
        self._legacy_extractor = legacy_extractor

    async def plan_queries(self, request: QueryExamplePlannerRequest) -> QueryExamplePlannerResult:
        """
        创建时间: 2026-04-30
        任务: level3-query-exampler-mainline
        说明: 旧 extractor 只负责产出描述性人物锚点；这里再统一收口成少量 query example，
              继续遵守新主线的 1-2 条 query 预算与 direct-first 语义。
        """

        mentions = await self._legacy_extractor.extract_mentions(
            MentionExtractionRequest(
                text=request.text,
                names_in_chunk=tuple(dict.fromkeys(request.requested_names + request.seed_entities)),
                context_text=request.text,
                run_id=request.run_id,
                current_chunk=request.current_chunk,
            )
        )
        all_queries = build_query_examples_from_mentions(
            [mention for mention in mentions if isinstance(mention, PersonMention)],
            query_source=None,
        )
        max_queries = min(max(request.max_queries, 0), 2)
        kept_queries = all_queries[:max_queries]
        dropped_queries = [
            {
                "query_text": query.query_text,
                "mention_text": query.anchor_text,
                "query_variant": query.query_variant,
                "reason": "max_queries_budget",
            }
            for query in all_queries[max_queries:]
        ]
        return QueryExamplePlannerResult(
            should_expand=bool(kept_queries),
            reason="legacy_mention_extractor_adapter",
            queries=kept_queries,
            dropped_queries=dropped_queries,
        )

    def resolve_audit_semantics(self, result: QueryExamplePlannerResult) -> tuple[QueryPlannerKind, bool]:
        """
        创建时间: 2026-04-30
        修改时间: 2026-04-30
        任务: fix-level3-query-example-review-findings
        新建原因: legacy compat 路径可能只返回规则抽取结果；
                  这类 query example 不能再被上游统一误记成一次真实的 LLM planner 命中。
        修改原因: legacy extractor 返回空列表时同样拿不到任何“真实调用了 LLM planner”的证据；
                  审计口径应继续保守，避免把无结果 compat path 误报成 LLM planner 命中。
        """

        if not result.queries:
            return "rule_example", False
        if all(query.query_source == "rule" for query in result.queries):
            return "rule_example", False
        return "llm_query_example", True


def _coerce_query_example_planner(planner: Any | None) -> Level3QueryExamplePlanner | None:
    """
    创建时间: 2026-04-30
    任务: level3-query-exampler-mainline
    说明: 兼容新旧两类注入对象：
          新对象直接实现 `plan_queries()`；旧对象若仍是 `extract_mentions()` 语义，
          则自动桥接成 query planner，避免分支切换期间 runtime 失配。
    """

    if planner is None:
        return None
    plan_queries = getattr(planner, "plan_queries", None)
    if callable(plan_queries):
        return planner
    extract_mentions = getattr(planner, "extract_mentions", None)
    if callable(extract_mentions):
        return _LegacyMentionExtractorQueryPlannerAdapter(planner)
    return planner


class NarrativeEvidenceService:
    """叙事证据服务（Evidence Service 层）

    负责接收统一的 EvidenceRequest，并编排三级证据为 EvidenceBundle：
    - Level1: 别名表精确映射
    - Level2: 近期活跃实体
    - Level3: 向量语义相似 chunk

    prompt block 的文本渲染仍留在 renderer 层；service 只负责取证编排
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
        query_example_planner: Level3QueryExamplePlanner | None = None,
        mention_extractor: Level3QueryExamplePlanner | None = None,
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
        # 修改时间: 2026-04-30
        # 任务: level3-query-exampler-mainline
        # 修改原因: transport 配置仍沿用 mention_extraction alias，
        #           但 identity 热路径的主职责已切换为 query example planner。
        self._llm_query_example_planner = _coerce_query_example_planner(query_example_planner or mention_extractor)
        self._level3_reranker = level3_reranker
        self._progress_emitter = progress_emitter
        self._bundle_cache: dict[tuple[object, ...], EvidenceBundle] = {}

    async def _emit_level3_progress(self, current_chunk: int | None, message: str, _sub_percent: float) -> None:
        """
        修改时间: 2026-04-30
        任务: level3-query-exampler-mainline
        修改原因: planner 主线新增了规则 gate / LLM fallback 这类关键观测语义，
                  progress 事件必须把调用方传入的 message/sub_percent 原样带出去，
                  否则排障时只能看到笼统的“正在收集证据”。
        """
        if self._progress_emitter is None:
            return
        await self._progress_emitter(
            StreamEvent(
                action="progress",
                stage="annotate",
                chunk_id=current_chunk,
                message=message,
                sub_percent=_sub_percent,
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
        说明: Level1 只按 request.requested_names 过滤；
              不再把 retrieval seed_entities 误当成“当前 consumer 真正要看的名字”
        """
        snapshot = self._get_authority_snapshot()
        return self._bundle_builder.build_structured_bundle(snapshot, requested_names=requested_names)

    def _build_request_meta(self, request: EvidenceRequest) -> dict[str, Any]:
        """
        说明: request_meta 直接记录调用方显式声明的输入边界，方便后续日志、回放和问题归因
        """
        return {
            "consumer": request.consumer,
            "objective": request.objective,
            "requested_names": list(request.requested_names),
            "seed_entities": list(request.seed_entities),
            "reference_slots": list(request.reference_slots),
            "background_entities": list(request.background_entities),
            "current_chunk": request.current_chunk,
            "max_chunk_id": request.max_chunk_id,
            "exclude_chunk_ids": list(request.exclude_chunk_ids),
        }

    def _build_generation_meta(self, request: EvidenceRequest) -> dict[str, Any]:
        """
        说明: generation_meta 统一承载本次 evidence 编排观察字段；
              即使某条路径没有真正执行 Level3，也保留稳定键名，避免观察面继续分裂
        """
        return {
            "need_level1": request.need_level1,
            "need_level2": request.need_level2,
            "need_level3": request.need_level3,
            "level3_executed": False,
            "query_mode": "disabled",
            "query_planner_kind": "disabled",
            "query_planner_reason": None,
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
        说明: cache 只复用 evidence 内容本身；每次命中后仍用当前 request 的 meta 重新打戳，
              避免 Phase1/Phase3 这类 consumer 复用时把上一跳标签带过去
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

    def _should_cache_bundle(self, bundle: EvidenceBundle) -> bool:
        """
        创建时间: 2026-04-30
        任务: fix-level3-query-example-review-findings
        新建原因: planner 的临时基础设施故障只能触发“当次 direct 保底”，
                  不能把 `llm_query_example_failed:*` 这种降级结果固化进后续同请求缓存。
        """
        planner_reason = str(bundle.generation_meta.get("query_planner_reason") or "").strip()
        if planner_reason.startswith("llm_query_example_failed:"):
            return False
        return True

    def _cache_bundle(self, request: EvidenceRequest, bundle: EvidenceBundle) -> None:
        """
        说明: service 级 cache 只按真实取证语义复用，供同一 chunk 内的多 consumer 复用相同 bundle
        """
        if not self._should_cache_bundle(bundle):
            logger.info(
                "skip caching unstable Level3 bundle: run_id={} consumer={} objective={} reason={}",
                self._run_id,
                request.consumer,
                request.objective,
                bundle.generation_meta.get("query_planner_reason"),
            )
            return
        cache_key = build_evidence_request_fingerprint(request)
        self._bundle_cache[cache_key] = bundle.clone_with_meta()

    def _collect_base_evidence(self, request: EvidenceRequest) -> EvidenceBundle:
        """
        收集 Level1/Level2 证据
        """
        if request.need_level1:
            bundle = self._build_structured_evidence(requested_names=request.requested_names)
        else:
            bundle = EvidenceBundle(
                structured_evidence=[],
                requested_names=list(request.requested_names),
                reference_slots=list(request.reference_slots),
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
        bundle.reference_slots = list(request.reference_slots)
        return bundle

    def _build_annotation_phase1_emotion_request(self, request: EvidenceRequest) -> EvidenceRequest:
        """
        说明: Phase1 对外只暴露 identity request；
              emotion overlay 的 query 由 service 内部派生，避免 workflow 再显式管理第二份 request
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
        说明: Phase1 的 emotion overlay 只改变最终返回 bundle，不改变 identity base recall；
              这里显式派生一个“无 overlay content variant”的请求键，供 Phase3 等纯 identity consumer
              复用同一份 Level3 base evidence，避免同 chunk 重复 embedding/检索/rerank
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
        说明: 统一执行单条 EvidenceRequest，不处理 annotation Phase1 的 overlay 特例；
              collect() 会在需要时用这个基础执行器拼出最终返回值
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
                # required Level3 语义下，入口已声明“没有 Level3 就不能继续”，
                # 因此 async readiness 漂移必须 fail loudly，不能偷偷退回 Level1/2
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

        query_count = len(plan.expansion_queries) + (1 if plan.base_query_text else 0)
        bundle.generation_meta.update(
            {
                "level3_executed": True,
                "query_mode": plan.mode,
                "query_planner_kind": plan.planner_kind,
                "query_planner_reason": plan.planner_reason,
                "query_count": query_count,
                "top_k": plan.top_k,
                "batch_mode": "batched" if query_count > 1 else "single",
                "failed_queries": failed_queries,
                "dropped_queries": list(plan.dropped_queries),
            }
        )
        logger.info(
            "Level3 evidence collection complete: run_id={} consumer={} objective={} chunk_id={} mode={} "
            "planner_kind={} expansion_queries={} results={} semantic_items={} duration_ms={}",
            self._run_id,
            request.consumer,
            request.objective,
            request.current_chunk,
            plan.mode,
            plan.planner_kind,
            len(plan.expansion_queries),
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
        收集统一 evidence bundle
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
            # 先把不带 emotion overlay 的 identity base 存进“普通 identity”缓存键，
            # 后续 annotation_phase3 命中同语义请求时即可直接复用，不必再跑一轮 Level3 热路径
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
        修改时间: 2026-04-30
        任务: level3-query-exampler-mainline
        说明: 先做 identity 二级门槛，再决定是否启用规则/LLM query planner；
              任意 LLM 调用都只能发生在 direct gate 之后。
        修改原因: direct gate 需要把“当前 consumer target 已在正文解析完成”作为稳定保底，
                  不能因为同段里还有旁观者锚点或同位语描述，就重新打开高阶 planner。
        """
        base_query_text = request.query_text.strip()
        direct_candidate_pool_k = self._level3_pool_k(request.top_k)
        if not base_query_text:
            return Level3QueryPlan(
                mode="direct",
                base_query_text="",
                expansion_queries=[],
                candidate_pool_k=direct_candidate_pool_k,
                top_k=request.top_k,
                planner_kind="disabled",
                planner_reason="query_text_empty",
            )
        if request.objective != "identity":
            return Level3QueryPlan(
                mode="direct",
                base_query_text=base_query_text,
                expansion_queries=[],
                candidate_pool_k=direct_candidate_pool_k,
                top_k=request.top_k,
                planner_kind="disabled",
                planner_reason="objective_not_identity",
            )
        if not request.allow_llm_query_expansion:
            return Level3QueryPlan(
                mode="direct",
                base_query_text=base_query_text,
                expansion_queries=[],
                candidate_pool_k=direct_candidate_pool_k,
                top_k=request.top_k,
                planner_kind="disabled",
                planner_reason="llm_query_expansion_disabled",
            )

        if self._are_all_requested_names_directly_mentioned(base_query_text, request.requested_names):
            return Level3QueryPlan(
                mode="direct",
                base_query_text=base_query_text,
                expansion_queries=[],
                candidate_pool_k=direct_candidate_pool_k,
                top_k=request.top_k,
                planner_kind="direct_gate",
                planner_reason="trusted_name_direct",
            )

        anchor_candidates = collect_descriptive_anchor_texts(
            base_query_text,
            names_in_chunk=tuple(dict.fromkeys(request.requested_names + request.seed_entities)),
            run_id=self._run_id,
            current_chunk=request.current_chunk,
        )
        if not anchor_candidates:
            return Level3QueryPlan(
                mode="direct",
                base_query_text=base_query_text,
                expansion_queries=[],
                candidate_pool_k=direct_candidate_pool_k,
                top_k=request.top_k,
                planner_kind="direct_gate",
                planner_reason="no_descriptive_anchor",
            )

        planner_request = self._build_query_example_planner_request(
            request,
            anchor_candidates=anchor_candidates,
        )
        if planner_request.max_queries <= 0:
            return Level3QueryPlan(
                mode="direct",
                base_query_text=base_query_text,
                expansion_queries=[],
                candidate_pool_k=direct_candidate_pool_k,
                top_k=request.top_k,
                planner_kind="rule_example",
                planner_reason="no_query_budget",
            )
        await self._emit_level3_progress(
            request.current_chunk,
            f"[{request.objective}] 正在规划 Level3 query example",
            15,
        )
        rule_result = build_rule_query_examples(planner_request)
        if rule_result.queries:
            await self._emit_level3_progress(
                request.current_chunk,
                f"[{request.objective}] 规则 exampler 产出 {len(rule_result.queries)} 条 query example",
                35,
            )
            return Level3QueryPlan(
                mode="hybrid",
                base_query_text=base_query_text,
                expansion_queries=rule_result.queries,
                candidate_pool_k=direct_candidate_pool_k,
                top_k=request.top_k,
                planner_kind="rule_example",
                planner_reason=rule_result.reason,
                dropped_queries=list(rule_result.dropped_queries),
            )
        if self._llm_query_example_planner is None:
            return Level3QueryPlan(
                mode="direct",
                base_query_text=base_query_text,
                expansion_queries=[],
                candidate_pool_k=direct_candidate_pool_k,
                top_k=request.top_k,
                planner_kind="rule_example",
                planner_reason=rule_result.reason,
                dropped_queries=list(rule_result.dropped_queries),
            )

        await self._emit_level3_progress(
            request.current_chunk,
            f"[{request.objective}] 规则 exampler 无结果，正在调用 LLM planner",
            25,
        )
        try:
            planner_result = await self._llm_query_example_planner.plan_queries(planner_request)
        except Exception as exc:
            logger.warning(
                "Level3 LLM query planner failed; falling back to direct query: run_id={} chunk_id={} error={}",
                self._run_id,
                request.current_chunk,
                exc,
            )
            await self._emit_level3_progress(
                request.current_chunk,
                f"[{request.objective}] LLM planner 失败，回退 direct query",
                35,
            )
            return Level3QueryPlan(
                mode="direct",
                base_query_text=base_query_text,
                expansion_queries=[],
                candidate_pool_k=direct_candidate_pool_k,
                top_k=request.top_k,
                planner_kind="llm_query_example",
                planner_reason=f"llm_query_example_failed:{exc.__class__.__name__}",
                llm_invoked=True,
                dropped_queries=list(rule_result.dropped_queries),
            )
        planner_kind, llm_invoked = self._resolve_query_planner_audit_semantics(planner_result)
        if planner_result.should_expand and planner_result.queries:
            await self._emit_level3_progress(
                request.current_chunk,
                f"[{request.objective}] LLM planner 产出 {len(planner_result.queries)} 条 query example",
                35,
            )
            return Level3QueryPlan(
                mode="hybrid",
                base_query_text=base_query_text,
                expansion_queries=planner_result.queries,
                candidate_pool_k=direct_candidate_pool_k,
                top_k=request.top_k,
                planner_kind=planner_kind,
                planner_reason=planner_result.reason,
                llm_invoked=llm_invoked,
                dropped_queries=list(planner_result.dropped_queries),
            )

        return Level3QueryPlan(
            mode="direct",
            base_query_text=base_query_text,
            expansion_queries=[],
            candidate_pool_k=direct_candidate_pool_k,
            top_k=request.top_k,
            planner_kind=planner_kind,
            planner_reason=planner_result.reason,
            llm_invoked=llm_invoked,
            dropped_queries=list(planner_result.dropped_queries),
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
        说明: 执行显式 query plan；retrieve / rerank / dedupe 仍保留在 provider 编排层，但不再直接耦合 workflow 弱参数
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
        说明: query planning 已外提后，这里只负责执行计划、重排候选并按请求预算裁剪
        """
        started_at = time.perf_counter()
        collected, failed_queries = await self._retrieve_candidates(
            plan=plan,
            request=request,
        )
        retrieved_ms = int((time.perf_counter() - started_at) * 1000)
        logger.info(
            "Level3 candidate retrieval complete: run_id={} objective={} chunk_id={} mode={} "
            "planner_kind={} expansion_queries={} candidates={} duration_ms={}",
            self._run_id,
            request.objective,
            request.current_chunk,
            plan.mode,
            plan.planner_kind,
            len(plan.expansion_queries),
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

    def _build_query_example_planner_request(
        self,
        request: EvidenceRequest,
        *,
        anchor_candidates: tuple[str, ...],
    ) -> QueryExamplePlannerRequest:
        """
        创建时间: 2026-04-30
        任务: level3-query-exampler-mainline
        说明: 统一把 EvidenceRequest 裁成 planner 可消费的最小上下文，
              避免 planner 继续耦合 workflow/runtime 的宽字段集合。
        """

        return QueryExamplePlannerRequest(
            text=request.query_text,
            requested_names=tuple(request.requested_names),
            seed_entities=tuple(request.seed_entities),
            anchor_candidates=anchor_candidates,
            run_id=self._run_id,
            current_chunk=request.current_chunk,
            max_queries=min(max(request.max_queries, 0), 2),
        )

    def _are_all_requested_names_directly_mentioned(self, query_text: str, requested_names: list[str]) -> bool:
        """
        创建时间: 2026-04-30
        修改时间: 2026-04-30
        任务: level3-query-exampler-mainline
        说明: direct gate 只把“当前 consumer target 已经全部在正文直出现”当作稳定保底信号；
              这样同段里的旁观者描述或同位语不会把已解析 target 再拉回高阶 planner。
        修改原因: 原先按“任一 requested_name 命中”判断过于宽松，既不能表达“target 全部已解析”，
                  也无法和 direct-first 的目标语义对齐。
        """

        normalized_query_text = query_text.strip()
        if not normalized_query_text:
            return False
        normalized_names = [name.strip() for name in requested_names if name.strip()]
        if not normalized_names:
            return False
        return all(self._has_strong_direct_name_surface(normalized_query_text, name) for name in normalized_names)

    def _has_strong_direct_name_surface(self, query_text: str, name: str) -> bool:
        """
        创建时间: 2026-04-30
        修改时间: 2026-04-30
        任务: fix-level3-query-example-review-findings
        新建原因: direct gate 需要保守识别“正文里真的直出了 target surface”，
                  不能把单字短 alias 或多字名字的部分重叠/后缀命中当成已解析 target。
        """

        normalized_name = name.strip()
        if not normalized_name or normalized_name not in query_text:
            return False
        if len(normalized_name) > 1:
            start = 0
            while True:
                matched_at = query_text.find(normalized_name, start)
                if matched_at < 0:
                    return False
                next_index = matched_at + len(normalized_name)
                next_char = query_text[next_index] if next_index < len(query_text) else ""
                if not self._is_name_overlap_suffix_char(next_char):
                    return True
                start = matched_at + 1

        start = 0
        while True:
            matched_at = query_text.find(normalized_name, start)
            if matched_at < 0:
                return False
            previous_char = query_text[matched_at - 1] if matched_at > 0 else ""
            next_index = matched_at + len(normalized_name)
            next_char = query_text[next_index] if next_index < len(query_text) else ""
            if not self._is_name_like_char(previous_char) and not self._is_name_like_char(next_char):
                return True
            start = matched_at + 1

    def _is_name_overlap_suffix_char(self, char: str) -> bool:
        """
        创建时间: 2026-04-30
        任务: fix-level3-query-example-review-findings
        新建原因: 多字名字的 direct gate 仍需挡住常见的昵称后缀/粘连 surface，
                  例如“白芷儿”这类并非正文直出 target surface 的重叠命中。
        """

        return char in {"儿", "子", "哥", "姐", "妹", "弟", "叔", "姨", "伯", "爷", "娘", "氏", "总"}

    def _is_name_like_char(self, char: str) -> bool:
        """
        创建时间: 2026-04-30
        任务: fix-level3-query-example-review-findings
        新建原因: 单字名字/别名的 direct gate 只能在边界清晰时命中；
                  相邻仍是中英文或数字时，更可能只是更长名字的一部分。
        """

        if not char:
            return False
        if char.isascii():
            return char.isalnum() or char == "_"
        return "\u4e00" <= char <= "\u9fff"

    def _resolve_query_planner_audit_semantics(
        self,
        result: QueryExamplePlannerResult,
    ) -> tuple[QueryPlannerKind, bool]:
        """
        创建时间: 2026-04-30
        任务: fix-level3-query-example-review-findings
        新建原因: query planner transport 仍可能经由 legacy `mention_extractor` alias 注入；
                  generation_meta 与 model_interactions 必须按实际 query source 记录，
                  不能把 rule compat 结果统一误报成 LLM planner 命中。
        """

        if isinstance(self._llm_query_example_planner, _LegacyMentionExtractorQueryPlannerAdapter):
            return self._llm_query_example_planner.resolve_audit_semantics(result)
        return "llm_query_example", True

    async def _retrieve_candidates(
        self,
        *,
        plan: Level3QueryPlan,
        request: EvidenceRequest,
    ) -> tuple[list[SimilarChunkRow], list[dict[str, object]]]:
        """
        说明: 按 query plan 执行粗召回；候选池预算统一由 plan.candidate_pool_k 控制
        """
        collected: list[SimilarChunkRow] = []
        failed_queries: list[dict[str, object]] = []
        retrieval_queries: list[tuple[str, Level3ExpansionQuery | None]] = [
            ("mention", expansion_query) for expansion_query in plan.expansion_queries
        ]
        if plan.base_query_text:
            retrieval_queries.append(("base", None))
        if not retrieval_queries:
            return collected, failed_queries
        retrieval_top_k = self._compute_per_query_retrieval_top_k(
            candidate_pool_k=plan.candidate_pool_k,
            query_count=len(retrieval_queries),
        )

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
        for index, ((query_kind, expansion_query), query_results) in enumerate(
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
                if expansion_query is not None:
                    failure_entry.update(
                        {
                            "mention_text": expansion_query.anchor_text,
                            "query_variant": expansion_query.query_variant,
                        }
                    )
                failed_queries.append(failure_entry)
            if query_kind == "mention" and expansion_query is not None:
                logger.debug(
                    "Level3 query example complete: run_id={} query_index={}/{} query_len={} results={} batched={}",
                    self._run_id,
                    index,
                    len(retrieval_queries),
                    len(expansion_query.query_text),
                    len(query_results),
                    len(query_texts) > 1,
                )
                collected.extend(
                    replace(
                        result,
                        query_kind="mention",
                        mention_text=expansion_query.anchor_text,
                        mention_type=expansion_query.anchor_type,
                        matched_features=expansion_query.matched_features,
                        mention_source=expansion_query.query_source,
                        mention_confidence=expansion_query.confidence,
                        query_variant=expansion_query.query_variant,
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

    def _compute_per_query_retrieval_top_k(self, *, candidate_pool_k: int, query_count: int) -> int:
        """
        创建时间: 2026-04-30
        任务: fix-level3-query-example-review-findings
        新建原因: `candidate_pool_k` 语义改为整份 plan 的粗召回总预算，
                  hybrid 路径必须把预算按 query 数拆分后再下发给 batched retrieval，
                  否则 query 数虽然减少了，总粗召回仍会继续按 query_count 成倍放大。
        """

        if query_count <= 0:
            return max(candidate_pool_k, 0)
        return max(candidate_pool_k // query_count, 1)

    async def _search_level3_queries(
        self,
        query_texts: list[str],
        *,
        exclude_chunk_ids: list[int] | None,
        max_chunk_id: int | None,
        top_k: int | None,
    ) -> tuple[list[list[SimilarChunkRow]], list[dict[str, object]]]:
        """
        说明: 多 query 时统一走 batched Level3 检索，单 query 仍复用既有入口，
              避免热路径继续逐条请求 embedding 服务
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
        说明: plan 决定是否存在高阶 query；只有 hybrid/high_order 情况才启用 deterministic mention rerank
        """
        collected = results
        if plan.expansion_queries:
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
        说明: 给模型 rerank 汇总原文 query 与 mention query，避免模型只看到压缩词而丢失当前语境
        """
        max_chars = max(int(request.model_rerank_query_max_chars), 0)
        if max_chars <= 0:
            return ""

        segments = self._collect_model_rerank_query_segments(plan)
        return self._render_model_rerank_query_segments(segments, max_chars=max_chars)

    def _collect_model_rerank_query_segments(self, plan: Level3QueryPlan) -> list[tuple[str, str]]:
        """
        说明: 为 model rerank 组装 query summary 片段；base query 保留语境，
              mention query 则优先选更短、更稳定的压缩/特征变体，避免重复拼入整段原文
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
        best_query_by_anchor: dict[str, Level3ExpansionQuery] = {}
        for query in plan.expansion_queries:
            anchor_key = query.anchor_text.strip() or query.query_text.strip()
            existing = best_query_by_anchor.get(anchor_key)
            if existing is None:
                best_query_by_anchor[anchor_key] = query
                continue
            current_priority = variant_priority.get(existing.query_variant, 99)
            next_priority = variant_priority.get(query.query_variant, 99)
            if next_priority < current_priority:
                best_query_by_anchor[anchor_key] = query
                continue
            if next_priority == current_priority and len(query.query_text) < len(existing.query_text):
                best_query_by_anchor[anchor_key] = query

        for mention_index, query in enumerate(best_query_by_anchor.values(), start=1):
            compact_query_text = " ".join(query.query_text.split())
            if compact_query_text:
                segments.append((f"q{mention_index}", compact_query_text))
        return segments

    def _render_model_rerank_query_segments(self, segments: list[tuple[str, str]], *, max_chars: int) -> str:
        """
        说明: 将 summary 片段压缩到固定字符预算内；这里按“每段至少保留最小摘要”的方式分配，
              避免 base query 吞掉全部 budget，或后续 mention summary 完全挤不进去
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
        说明: 对单条 rerank query 片段做最小压缩；优先保留前缀关键信息，超长时用省略号截断
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
        说明: 包装 Level3 query 调用；仅在 mention retrieval 需要扩大召回池时传入 top_k
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
        说明: 对多 query 的 Level3 结果按 chunk_id 去重；同分时优先保留 mention 来源，方便后续观察
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
        说明: 统一读取 Level3 排序分，确保 rerank 与旧 similarity 排序路径共用同一比较逻辑
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
        说明: Level3 候选池预算不再由各路径各自推断，而是统一从 final top_k 派生
        """
        return max(top_k * 4, 20)

    def _extract_active_entity_names(self, bundle: EvidenceBundle) -> set[str]:
        """
        说明: 从 Level2 evidence 中提取活跃实体名，作为 rerank 加权输入，不额外查询数据库
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
        """检查当前 provider 是否按当前流程配置要求启用 Level 3"""
        return self._level3_enabled

    async def ensure_level3_ready(self) -> None:
        if self._level3_enabled:
            await self._level3.ensure_level3_ready()
