"""
说明: 本模块提供统一证据收集功能
- Level1: 别名表精确匹配
- Level2: 活跃实体候选
- 历史取证: keyword、semantic、read 三种模式
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
        self._level3 = Level3VectorEvidence(
            session=session,
            run_id=run_id,
            embedding_client=embedding_client,
            similarity_threshold=similarity_threshold,
            top_k=level3_top_k,
            expected_embedding_dim=settings.models.paragraph_embedding.embedding_dim,
        )

        self._run_id = run_id
        self._session = session
        self._lookback_chunks = lookback_chunks
        self._authority_snapshot_cache: Level1AuthoritySnapshot | None = None
        self._graph_authority_service = KnowledgeGraphAuthorityService(graph_repo) if graph_repo is not None else None
        self._level1_enabled = level1_enabled
        self._level2_enabled = level2_enabled
        self._level3_enabled = level3_enabled
        self._level3_top_k = level3_top_k
        self._bundle_builder = EvidenceBundleBuilder()
        self._progress_emitter = progress_emitter
        self._bundle_cache: dict[tuple[object, ...], EvidenceBundle] = {}
        self._historical_authorizations: dict[tuple[str, str, int | None], set[int]] = {}

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
        self._session = session
        if self._run_id:
            self._level3.set_session(session, self._run_id)

    def invalidate_cache(self) -> None:
        """别名映射和关系缓存失效（每个 chunk 处理后调用，因为 projection 可能更新了别名表）"""
        self._authority_snapshot_cache = None
        self._bundle_cache.clear()
        self._historical_authorizations.clear()

    def _get_authority_snapshot(self) -> Level1AuthoritySnapshot:
        if not self._level1_enabled or self._graph_authority_service is None or self._run_id is None:
            return Level1AuthoritySnapshot()
        if self._authority_snapshot_cache is None:
            self._authority_snapshot_cache = self._graph_authority_service.build_level1_snapshot(self._run_id)
        return self._authority_snapshot_cache

    def _build_structured_evidence(self, requested_names: list[str] | None = None) -> EvidenceBundle:
        """Level1 只按 request.requested_names 过滤"""
        snapshot = self._get_authority_snapshot()
        return self._bundle_builder.build_structured_bundle(snapshot, requested_names=requested_names)

    def _build_request_meta(self, request: EvidenceRequest) -> dict[str, Any]:
        """记录请求输入与服务统一派生的历史边界"""
        return {
            "consumer": request.consumer,
            "objective": request.objective,
            "retrieval_method": request.mode,
            "query_text": request.query_text,
            "keywords": list(request.keywords),
            "read_chunk_id": request.read_chunk_id,
            "requested_names": list(request.requested_names),
            "seed_entities": list(request.seed_entities),
            "reference_slots": list(request.reference_slots),
            "background_entities": list(request.background_entities),
            "request_observation": dict(request.request_observation),
            "current_chunk": request.current_chunk,
            "max_chunk_id": request.historical_max_chunk_id(),
            "exclude_chunk_ids": list(request.historical_exclude_chunk_ids()),
        }

    def _build_generation_meta(self, request: EvidenceRequest) -> dict[str, Any]:
        """记录本次证据编排和历史取证模式的观察字段"""
        return {
            "need_level1": request.need_level1,
            "need_level2": request.need_level2,
            "retrieval_method": request.mode,
            "historical_executed": False,
            "keyword_executed": False,
            "semantic_executed": False,
            "read_executed": False,
            "query_count": 0,
            "top_k": request.top_k,
            "cache_reuse": False,
            "historical_skipped_reason": None,
            "read_status": None,
        }

    def _restore_cached_bundle(self, request: EvidenceRequest) -> EvidenceBundle | None:
        """复用证据内容并用当前请求重新打戳"""
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
        """按真实取证语义缓存证据结果"""
        cache_key = build_evidence_request_fingerprint(request)
        self._bundle_cache[cache_key] = bundle.clone_with_meta()

    def _authorization_key(self, request: EvidenceRequest) -> tuple[str, str, int | None]:
        """生成当前 Agent 会话的历史读取授权作用域"""
        return request.consumer, request.objective, request.current_chunk

    def _remember_historical_chunks(self, request: EvidenceRequest, bundle: EvidenceBundle) -> None:
        """登记本次 keyword 或 semantic 结果可展开的历史 chunk"""
        chunk_ids = {
            item.chunk_id
            for item in bundle.historical_evidence
            if item.chunk_id is not None and item.retrieval_method in {"keyword", "semantic"}
        }
        if chunk_ids:
            self._historical_authorizations.setdefault(self._authorization_key(request), set()).update(chunk_ids)

    def _is_read_authorized(self, request: EvidenceRequest) -> bool:
        """检查 read 请求是否通过当前 chunk 和同 objective 的定位授权"""
        target_chunk_id = request.read_chunk_id
        current_chunk_id = request.current_chunk
        if target_chunk_id is None or current_chunk_id is None:
            return False
        if target_chunk_id < 0 or target_chunk_id >= current_chunk_id:
            return False
        authorized_chunks = self._historical_authorizations.get(self._authorization_key(request), set())
        return target_chunk_id in authorized_chunks

    def _effective_top_k(self, request: EvidenceRequest) -> int:
        """计算历史检索使用的有效 top_k"""
        default_top_k = self._level3_top_k if request.mode == "semantic" else 10
        return max(1, request.top_k or default_top_k)

    def _collect_base_evidence(self, request: EvidenceRequest) -> EvidenceBundle:
        """收集 Level1/Level2 证据"""
        if request.need_level1:
            bundle = self._build_structured_evidence(requested_names=request.requested_names)
        else:
            bundle = EvidenceBundle(
                structured_evidence=[],
                requested_names=list(request.requested_names),
                reference_slots=list(request.reference_slots),
            )

        if request.need_level2 and self._level2_enabled and request.current_chunk is not None:
            if self._graph_authority_service is not None and self._run_id is not None:
                active_entities = self._graph_authority_service.build_active_entity_view(
                    self._run_id,
                    current_chunk=request.current_chunk,
                    lookback=self._lookback_chunks,
                )
            else:
                active_entities = []

            bundle.local_evidence.extend(self._bundle_builder.build_active_entity_items(active_entities))

        bundle.requested_names = list(request.requested_names)
        bundle.reference_slots = list(request.reference_slots)
        return bundle

    async def collect(self, request: EvidenceRequest) -> EvidenceBundle:
        """统一收集结构化、导航和历史证据"""
        cached_bundle = self._restore_cached_bundle(request)
        if cached_bundle is not None:
            if request.mode in {"keyword", "semantic"}:
                self._remember_historical_chunks(request, cached_bundle)
            return cached_bundle

        bundle = self._collect_base_evidence(request)
        bundle.request_meta = self._build_request_meta(request)
        bundle.generation_meta = self._build_generation_meta(request)

        if request.mode is None:
            self._cache_bundle(request, bundle)
            return bundle

        if request.mode == "keyword":
            self._collect_keyword_evidence(request, bundle)
            self._cache_bundle(request, bundle)
            return bundle
        if request.mode == "read":
            self._collect_read_evidence(request, bundle)
            if bundle.generation_meta["read_status"] == "success":
                self._cache_bundle(request, bundle)
            return bundle
        if request.mode == "semantic":
            await self._collect_semantic_evidence(request, bundle)
            self._cache_bundle(request, bundle)
            return bundle
        raise ValueError(f"Unsupported evidence retrieval method: {request.mode}")

    def _collect_keyword_evidence(self, request: EvidenceRequest, bundle: EvidenceBundle) -> None:
        """从 chunks.text 收集关键词历史自然段证据"""
        if not request.keywords:
            bundle.generation_meta["historical_skipped_reason"] = "keywords_empty"
            return
        if self._session is None or self._run_id is None:
            bundle.generation_meta["historical_skipped_reason"] = "storage_unavailable"
            return

        from src.storage.repositories.chunk import search_paragraphs_by_keywords

        matches = search_paragraphs_by_keywords(
            self._session,
            self._run_id,
            request.keywords,
            top_k=self._effective_top_k(request),
            exclude_chunk_ids=request.historical_exclude_chunk_ids(),
            max_chunk_id=request.historical_max_chunk_id(),
        )
        bundle.historical_evidence.extend(self._bundle_builder.build_keyword_recall_items(matches))
        bundle.generation_meta.update(
            {
                "historical_executed": True,
                "keyword_executed": True,
                "query_count": 1,
                "top_k": self._effective_top_k(request),
            }
        )
        self._remember_historical_chunks(request, bundle)

    def _collect_read_evidence(self, request: EvidenceRequest, bundle: EvidenceBundle) -> None:
        """按当前 Agent 作用域授权读取已定位的历史 chunk"""
        if not self._is_read_authorized(request):
            bundle.generation_meta.update(
                {
                    "read_status": "blocked_by_policy",
                    "historical_skipped_reason": "read_not_authorized",
                }
            )
            return
        if self._session is None or self._run_id is None:
            bundle.generation_meta.update(
                {
                    "read_status": "unavailable",
                    "historical_skipped_reason": "storage_unavailable",
                }
            )
            return

        from src.storage.repositories.chunk import fetch_chunk_text

        target_chunk_id = request.read_chunk_id
        if target_chunk_id is None:
            bundle.generation_meta.update(
                {
                    "read_status": "blocked_by_policy",
                    "historical_skipped_reason": "read_chunk_missing",
                }
            )
            return
        text = fetch_chunk_text(self._session, self._run_id, target_chunk_id)
        if text is None:
            bundle.generation_meta.update(
                {
                    "read_status": "empty",
                    "historical_skipped_reason": "chunk_not_found",
                }
            )
            return

        bundle.historical_evidence.append(self._bundle_builder.build_chunk_read_item(target_chunk_id, text))
        bundle.generation_meta.update(
            {
                "historical_executed": True,
                "read_executed": True,
                "read_status": "success",
                "query_count": 1,
            }
        )

    async def _collect_semantic_evidence(
        self,
        request: EvidenceRequest,
        bundle: EvidenceBundle,
    ) -> None:
        """在实际 semantic 请求时执行 Level3 readiness 和段落向量检索"""
        if not request.query_text:
            bundle.generation_meta["historical_skipped_reason"] = "query_text_empty"
            return
        if not self._level3_enabled:
            raise Level3NotReadyError("Semantic historical retrieval is disabled")

        started_at = time.perf_counter()
        top_k = self._effective_top_k(request)
        logger.info(
            "Semantic historical evidence collection start: run_id={} consumer={} objective={} chunk_id={} "
            "query_len={} max_chunk_id={} top_k={}",
            self._run_id,
            request.consumer,
            request.objective,
            request.current_chunk,
            len(request.query_text),
            request.historical_max_chunk_id(),
            top_k,
        )
        await self._emit_level3_progress(
            request.current_chunk,
            f"[{request.objective}] 正在准备语义历史证据",
            30,
        )
        try:
            await self._level3.ensure_level3_ready()
            results = await self._level3.search_similar_paragraphs(
                request.query_text,
                exclude_chunk_ids=request.historical_exclude_chunk_ids(),
                max_chunk_id=request.historical_max_chunk_id(),
                top_k=top_k,
                ensure_ready=False,
            )
        except Level3NotReadyError as exc:
            bundle.generation_meta["historical_skipped_reason"] = "readiness_failed"
            logger.error("Semantic historical retrieval readiness failed: {}", exc)
            raise

        bundle.historical_evidence.extend(self._bundle_builder.build_paragraph_recall_items(results))
        bundle.generation_meta.update(
            {
                "historical_executed": True,
                "semantic_executed": True,
                "query_count": 1,
                "top_k": top_k,
            }
        )
        self._remember_historical_chunks(request, bundle)
        logger.info(
            "Semantic historical evidence collection complete: run_id={} consumer={} objective={} chunk_id={} "
            "paragraphs={} historical_items={} duration_ms={}",
            self._run_id,
            request.consumer,
            request.objective,
            request.current_chunk,
            len(results),
            len(bundle.historical_evidence),
            int((time.perf_counter() - started_at) * 1000),
        )
        await self._emit_level3_progress(
            request.current_chunk,
            f"[{request.objective}] 语义历史证据准备完成：召回 {len(results)} 条",
            100,
        )

    def is_level3_available(self) -> bool:
        """检查 Level 3 是否可用"""
        return self._level3_enabled and self._level3.is_available()

    def requires_level3(self) -> bool:
        """检查当前 provider 是否按当前流程配置要求启用 Level 3"""
        return self._level3_enabled

    async def ensure_level3_ready(self) -> None:
        if self._level3_enabled:
            await self._level3.ensure_level3_ready()
