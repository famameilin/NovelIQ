"""
说明: 本模块提供证据收集功能（Provider 层），支持三级证据：
- Level1: 别名表精确匹配
- Level2: 活跃实体候选
- Level3: 自然段级向量语义相似度检索（RAG 粒度固定为一个自然段）
输出统一 EvidenceBundle，由下游 renderer 渲染为 prompt 内容
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from loguru import logger

from src.api.models.events import StreamEvent
from src.config import settings
from src.knowledge.authority import KnowledgeGraphAuthorityService
from src.rag.authority import Level1AuthorityProvider
from src.rag.evidence_bundle_builder import EvidenceBundleBuilder
from src.rag.evidence_contracts import (
    EvidenceRequest,
    build_evidence_request_fingerprint,
)
from src.rag.evidence_types import EvidenceBundle, Level1AuthoritySnapshot
from src.rag.level1_alias import AliasLookup
from src.rag.level2_active_entities import ActiveEntityLookup
from src.rag.level3_vector import Level3NotReadyError, Level3VectorEvidence

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.models.local.embedding import EmbeddingClient
    from src.storage.repositories import GraphRepository

__all__ = [
    "AliasLookup",
    "ActiveEntityLookup",
    "Level3NotReadyError",
    "Level3VectorEvidence",
    "NarrativeEvidenceService",
]


class NarrativeEvidenceService:
    """叙事证据服务（Evidence Service 层）

    负责接收统一的 EvidenceRequest，并编排三级证据为 EvidenceBundle：
    - Level1: 别名表精确映射
    - Level2: 近期活跃实体
    - Level3: 自然段级向量语义相似度检索

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
            expected_embedding_dim=settings.models.paragraph_embedding.embedding_dim,
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
        self._progress_emitter = progress_emitter
        self._bundle_cache: dict[tuple[object, ...], EvidenceBundle] = {}

    async def _emit_level3_progress(self, current_chunk: int | None, message: str, sub_percent: float) -> None:
        """发送 Level3 取证的进度事件"""
        if self._progress_emitter is None:
            return
        await self._progress_emitter(
            StreamEvent(
                action="progress",
                stage="annotate",
                chunk_id=current_chunk,
                message=message,
                sub_percent=sub_percent,
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
        """Level1 只按 request.requested_names 过滤"""
        snapshot = self._get_authority_snapshot()
        return self._bundle_builder.build_structured_bundle(snapshot, requested_names=requested_names)

    def _build_request_meta(self, request: EvidenceRequest) -> dict[str, Any]:
        """request_meta 直接记录调用方显式声明的输入边界"""
        return {
            "consumer": request.consumer,
            "objective": request.objective,
            "requested_names": list(request.requested_names),
            "seed_entities": list(request.seed_entities),
            "reference_slots": list(request.reference_slots),
            "background_entities": list(request.background_entities),
            "request_observation": dict(request.request_observation),
            "current_chunk": request.current_chunk,
            "max_chunk_id": request.max_chunk_id,
            "exclude_chunk_ids": list(request.exclude_chunk_ids),
        }

    def _build_generation_meta(self, request: EvidenceRequest) -> dict[str, Any]:
        """generation_meta 统一承载本次 evidence 编排观察字段"""
        return {
            "need_level1": request.need_level1,
            "need_level2": request.need_level2,
            "need_level3": request.need_level3,
            "level3_executed": False,
            "query_count": 0,
            "top_k": request.top_k,
            "cache_reuse": False,
            "level3_skipped_reason": None,
        }

    def _restore_cached_bundle(self, request: EvidenceRequest) -> EvidenceBundle | None:
        """cache 只复用 evidence 内容本身；命中后仍用当前 request 的 meta 重新打戳"""
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
        """service 级 cache 只按真实取证语义复用"""
        cache_key = build_evidence_request_fingerprint(request)
        self._bundle_cache[cache_key] = bundle.clone_with_meta()

    def _collect_base_evidence(self, request: EvidenceRequest) -> EvidenceBundle:
        """收集 Level1/Level2 证据"""
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

    async def collect(self, request: EvidenceRequest) -> EvidenceBundle:
        """收集统一 evidence bundle"""
        cached_bundle = self._restore_cached_bundle(request)
        if cached_bundle is not None:
            return cached_bundle

        bundle = self._collect_base_evidence(request)
        bundle.request_meta = self._build_request_meta(request)
        bundle.generation_meta = self._build_generation_meta(request)

        if not request.need_level3:
            self._cache_bundle(request, bundle)
            return bundle

        if not request.query_text:
            bundle.generation_meta["level3_skipped_reason"] = "query_text_empty"
            self._cache_bundle(request, bundle)
            return bundle

        if not self.is_level3_available():
            if self.requires_level3():
                raise RuntimeError("Level 3 paragraph retrieval is required but not available")
            bundle.generation_meta["level3_skipped_reason"] = "level3_unavailable"
            self._cache_bundle(request, bundle)
            return bundle

        started_at = time.perf_counter()
        logger.info(
            "Level3 paragraph evidence collection start: run_id={} consumer={} objective={} chunk_id={} "
            "requested_names={} seed_entities={} query_len={} max_chunk_id={} top_k={}",
            self._run_id,
            request.consumer,
            request.objective,
            request.current_chunk,
            len(request.requested_names),
            len(request.seed_entities),
            len(request.query_text),
            request.max_chunk_id,
            request.top_k,
        )
        await self._emit_level3_progress(
            request.current_chunk,
            f"[{request.objective}] 正在准备 Level3 段落证据",
            30,
        )
        try:
            await self._level3.ensure_level3_ready()
            results = await self._level3.search_similar_paragraphs(
                request.query_text,
                exclude_chunk_ids=request.exclude_chunk_ids,
                max_chunk_id=request.max_chunk_id,
                top_k=request.top_k or self._level3_top_k,
                ensure_ready=False,
            )
        except Level3NotReadyError as exc:
            if self.requires_level3():
                logger.error("Level3 readiness drift surfaced on required path: {}", exc)
                raise
            logger.warning("Level3 skipped during evidence collection: {}", exc)
            bundle.generation_meta["level3_skipped_reason"] = "readiness_failed"
            self._cache_bundle(request, bundle)
            return bundle

        bundle.semantic_evidence.extend(self._bundle_builder.build_paragraph_recall_items(results))
        bundle.generation_meta.update(
            {
                "level3_executed": True,
                "query_count": 1,
                "top_k": request.top_k or self._level3_top_k,
            }
        )
        logger.info(
            "Level3 paragraph evidence collection complete: run_id={} consumer={} objective={} chunk_id={} "
            "paragraphs={} semantic_items={} duration_ms={}",
            self._run_id,
            request.consumer,
            request.objective,
            request.current_chunk,
            len(results),
            len(bundle.semantic_evidence),
            int((time.perf_counter() - started_at) * 1000),
        )
        await self._emit_level3_progress(
            request.current_chunk,
            f"[{request.objective}] Level3 段落证据准备完成：召回 {len(results)} 条",
            100,
        )

        self._cache_bundle(request, bundle)
        return bundle

    def _extract_active_entity_names(self, bundle: EvidenceBundle) -> set[str]:
        """从 Level2 evidence 中提取活跃实体名"""
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
