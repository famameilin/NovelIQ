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

from dataclasses import replace
from typing import TYPE_CHECKING

from src.config import settings
from src.knowledge.authority import KnowledgeGraphAuthorityService
from src.rag.authority import Level1AuthorityProvider
from src.rag.evidence_bundle_builder import EvidenceBundleBuilder
from src.rag.evidence_types import EvidenceBundle, Level1AuthoritySnapshot
from src.rag.level1_alias import AliasLookup
from src.rag.level2_active_entities import ActiveEntityLookup
from src.rag.level3_vector import Level3NotReadyError, Level3VectorEvidence
from src.rag.mention_rerank import rerank_mention_level3_results

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
    ):
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

    async def collect_evidence_with_level3(
        self,
        names_in_chunk: list[str] | None = None,
        current_chunk: int | None = None,
        context_text: str | None = None,
        exclude_chunk_ids: list[int] | None = None,
        max_chunk_id: int | None = None,
        mention_queries: list[MentionEvidenceQuery] | None = None,
    ) -> EvidenceBundle:
        """
        收集 Level1/2/3 证据。

        修改时间: 2026-04-23
        任务: level3-history-cutoff
        修改说明: 增加 max_chunk_id 透传，调用方可显式声明 Level3 历史截止边界。

        修改时间: 2026-04-23
        任务: level3-mention-retrieval
        修改说明: 支持 mention_queries；mention 召回结果仅通过 metadata 标记来源，不扩张 prompt contract。
        """
        bundle = self.collect_evidence(names_in_chunk=names_in_chunk, current_chunk=current_chunk)

        if self._level3_enabled and self.is_level3_available():
            level3_results = await self._collect_level3_results(
                context_text=context_text,
                exclude_chunk_ids=exclude_chunk_ids,
                max_chunk_id=max_chunk_id,
                mention_queries=mention_queries,
                active_entity_names=self._extract_active_entity_names(bundle),
                candidate_names=set(bundle.requested_names),
                current_chunk=current_chunk,
            )
            bundle.semantic_evidence.extend(self._bundle_builder.build_semantic_recall_items(level3_results))
            bundle.semantic_evidence.extend(self._bundle_builder.build_emotion_exemplar_items(level3_results))

        return bundle

    async def _collect_level3_results(
        self,
        *,
        context_text: str | None,
        exclude_chunk_ids: list[int] | None,
        max_chunk_id: int | None,
        mention_queries: list[MentionEvidenceQuery] | None,
        active_entity_names: set[str],
        candidate_names: set[str],
        current_chunk: int | None,
    ) -> list[SimilarChunkRow]:
        """
        创建时间: 2026-04-23
        任务: level3-mention-retrieval
        说明: 统一执行 chunk query 与 mention query，并按 chunk_id 去重后限制证据预算。

        修改时间: 2026-04-24
        任务: level3-mention-rerank
        修改说明: mention 检索使用更大的召回池，并在去重前应用可解释的确定性 rerank。
        """
        collected: list[SimilarChunkRow] = []
        has_mention_queries = bool(mention_queries)
        retrieval_top_k = self._level3_pool_k() if has_mention_queries else None

        for mention_query in mention_queries or []:
            results = await self._search_level3_query(
                mention_query.query_text,
                exclude_chunk_ids=exclude_chunk_ids,
                max_chunk_id=max_chunk_id,
                top_k=retrieval_top_k,
            )
            collected.extend(
                replace(
                    result,
                    query_kind="mention",
                    mention_text=mention_query.mention_text,
                    mention_type=mention_query.mention_type,
                    matched_features=mention_query.matched_features,
                )
                for result in results
            )

        if context_text:
            collected.extend(
                await self._search_level3_query(
                    context_text,
                    exclude_chunk_ids=exclude_chunk_ids,
                    max_chunk_id=max_chunk_id,
                    top_k=retrieval_top_k,
                )
            )

        if has_mention_queries:
            collected = rerank_mention_level3_results(
                collected,
                active_entity_names=active_entity_names,
                candidate_names=candidate_names,
                current_chunk=current_chunk,
            )
        return self._dedupe_level3_results(collected)

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
            )
        return await self._level3.search_similar_chunks(
            query_text,
            exclude_chunk_ids=exclude_chunk_ids,
            max_chunk_id=max_chunk_id,
            top_k=top_k,
        )

    def _dedupe_level3_results(self, results: list[SimilarChunkRow]) -> list[SimilarChunkRow]:
        """
        创建时间: 2026-04-23
        任务: level3-mention-retrieval
        说明: 对多 query 的 Level3 结果按 chunk_id 去重；同分时优先保留 mention 来源，方便后续观察。

        修改时间: 2026-04-24
        任务: level3-mention-rerank
        修改说明: 若存在 rerank_score，则按 rerank 后分数去重和排序；否则保持原 similarity 语义。
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
        return ordered[: self._level3_top_k]

    def _level3_rank_score(self, result: SimilarChunkRow) -> float:
        """
        创建时间: 2026-04-24
        任务: level3-mention-rerank
        说明: 统一读取 Level3 排序分，确保 rerank 与旧 similarity 排序路径共用同一比较逻辑。
        """
        return result.rerank_score if result.rerank_score is not None else result.similarity

    def _level3_pool_k(self) -> int:
        """
        创建时间: 2026-04-24
        任务: level3-mention-rerank
        说明: mention rerank 先扩大召回池，再裁剪回 prompt top_k，避免只重排过小候选集。
        """
        return max(self._level3_top_k * 4, 20)

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
