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

说明: 本模块提供消歧上下文检索功能，支持三级检索：
- Level1: 别名表精确匹配
- Level2: 活跃实体候选
- Level3: 向量语义相似度检索
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loguru import logger

from src.config import settings
from src.rag.evidence_types import EvidenceBundle, EvidenceItem

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.models.local.embedding import EmbeddingClient
    from src.storage.repositories import GraphRepository


@dataclass
class DisambigResult:
    """消歧上下文查询结果"""

    level1_hit: bool = False
    level2_candidates: list[str] = field(default_factory=list)
    level3_evidence: str = ""
    canonical_name: str | None = None
    used_levels: list[int] = field(default_factory=list)


class Level3NotReadyError(RuntimeError):
    """Level 3 向量检索未就绪。"""


class AliasLookup:
    """Level1: 别名表精确匹配（带缓存）"""

    def __init__(
        self,
        graph_repo: GraphRepository | None = None,
        run_id: str | None = None,
    ):
        self._graph_repo = graph_repo
        self._run_id = run_id
        self._cache: dict[str, str] | None = None

    def _ensure_cache(self) -> dict[str, str]:
        if self._cache is None:
            if self._graph_repo is None or self._run_id is None:
                self._cache = {}
            else:
                self._cache = self._graph_repo.fetch_alias_map(self._run_id)
        return self._cache

    def invalidate_cache(self) -> None:
        self._cache = None

    def query(self, alias: str) -> str | None:
        canonical = self._ensure_cache().get(alias)
        if canonical:
            logger.debug(f"AliasLookup: '{alias}' -> '{canonical}'")
        return canonical

    def get_alias_map(self) -> dict[str, str]:
        """返回当前缓存的完整别名映射（只读副本）。"""
        return dict(self._ensure_cache())


class ActiveEntityLookup:
    """Level2: 近期活跃实体候选"""

    def __init__(self, graph_repo: GraphRepository | None = None, run_id: str | None = None):
        self._graph_repo = graph_repo
        self._run_id = run_id

    def get_active_candidates(
        self,
        current_chunk: int,
        lookback: int = 10,
    ) -> list[str]:
        if self._graph_repo is None or self._run_id is None:
            return []
        rows = self._graph_repo.fetch_active_entities(current_chunk, lookback, self._run_id)
        return [str(row["name"]) for row in rows]


class Level3VectorEvidence:
    """
    Level3: 向量语义相似度检索

    使用 EmbeddingClient 和 pgvector 进行语义相似度检索，
    发现跨 chunk 的隐式身份关联（如"灰衣人 = 白芷"）。
    """

    def __init__(
        self,
        session: Session | None = None,
        run_id: str | None = None,
        embedding_client: EmbeddingClient | None = None,
        similarity_threshold: float = 0.7,
        top_k: int = 5,
        expected_embedding_dim: int | None = None,
    ):
        self._session = session
        self._run_id = run_id
        self._embedding_client = embedding_client
        self._similarity_threshold = similarity_threshold
        self._top_k = top_k
        self._available: bool | None = None
        self._expected_embedding_dim = expected_embedding_dim or settings.models.semantic_chunking.embedding_dim
        self._setup_checked = False

    def set_embedding_client(self, client: EmbeddingClient) -> None:
        """设置 Embedding 客户端"""
        self._embedding_client = client
        self._available = None
        self._setup_checked = False

    def set_session(self, session: Session, run_id: str) -> None:
        """设置数据库会话"""
        self._session = session
        self._run_id = run_id
        self._available = None
        self._setup_checked = False

    async def ensure_level3_ready(self) -> None:
        if self._setup_checked:
            return

        if self._embedding_client is None or self._session is None or self._run_id is None:
            raise Level3NotReadyError("Level 3 requires embedding client, session, and run_id")

        actual_dim = await self._embedding_client.detect_embedding_dimension()
        if actual_dim != self._expected_embedding_dim:
            raise Level3NotReadyError(
                "Level 3 embedding dimension mismatch: "
                f"configured={self._expected_embedding_dim}, actual={actual_dim}"
            )

        from src.storage.repositories.chunk import has_embeddings
        from src.storage.vector_schema import validate_chunk_embeddings_schema

        validate_chunk_embeddings_schema(self._session, self._expected_embedding_dim)
        if not has_embeddings(self._session, self._run_id):
            raise Level3NotReadyError(f"Level 3 embeddings not found for run_id={self._run_id}")

        self._available = True
        self._setup_checked = True

    def is_available(self) -> bool:
        """
        检查 Level 3 是否可用

        Returns:
            True 如果 EmbeddingClient 已配置且数据库有 embedding 数据
        """
        if self._available is not None:
            return self._available

        if self._embedding_client is None:
            logger.debug("Level3VectorEvidence: EmbeddingClient not configured")
            self._available = False
            return False

        if self._session is None or self._run_id is None:
            logger.debug("Level3VectorEvidence: session or run_id not set")
            self._available = False
            return False

        from src.storage.repositories.chunk import has_embeddings

        self._available = has_embeddings(self._session, self._run_id)
        if self._available:
            logger.debug("Level3VectorEvidence: available, embeddings found in database")
        else:
            logger.debug("Level3VectorEvidence: no embeddings in database")
        return self._available

    async def search_similar_chunks(
        self,
        query_text: str,
        exclude_chunk_ids: list[int] | None = None,
    ) -> list[dict]:
        """
        检索语义相似的历史 chunk

        Args:
            query_text: 查询文本（通常是当前 chunk 的描述性文本）
            exclude_chunk_ids: 排除的 chunk ID 列表（通常是当前 chunk）

        Returns:
            相似 chunk 列表，每个元素包含 chunk_id, similarity, text
        """
        await self.ensure_level3_ready()

        if not self.is_available():
            return []

        if not query_text or not query_text.strip():
            logger.debug("Level3VectorEvidence: empty query text")
            return []

        if self._embedding_client is None or self._session is None or self._run_id is None:
            return []

        try:
            from src.storage.repositories.chunk import search_similar_chunks

            query_embedding = await self._embedding_client.get_embedding(query_text)
            if not query_embedding:
                logger.warning("Level3VectorEvidence: failed to get query embedding")
                return []

            results = search_similar_chunks(
                self._session,
                self._run_id,
                query_embedding,
                top_k=self._top_k,
                similarity_threshold=self._similarity_threshold,
                exclude_chunk_ids=exclude_chunk_ids,
            )

            logger.debug(
                f"Level3VectorEvidence: found {len(results)} similar chunks for query (len={len(query_text)})"
            )

            return results

        except Exception as e:
            logger.error(f"Level3VectorEvidence: search failed: {e}")
            return []

    def format_evidence_for_prompt(
        self,
        results: list[dict],
        max_chunks: int = 3,
        max_text_len: int = 200,
    ) -> str:
        """
        将检索结果格式化为 prompt 证据

        Args:
            results: 检索结果列表
            max_chunks: 最大展示 chunk 数
            max_text_len: 每个 chunk 文本的最大长度

        Returns:
            格式化的证据字符串
        """
        if not results:
            return ""

        evidence_parts = []
        for r in results[:max_chunks]:
            text = r.get("text", "")
            similarity = r.get("similarity", 0.0)
            chunk_id = r.get("chunk_id", 0)
            text_preview = text[:max_text_len] + "..." if len(text) > max_text_len else text
            evidence_parts.append(
                f"[Chunk {chunk_id}] (相似度: {similarity:.2f})\n{text_preview}"
            )

        return (
            "<Vector_Evidence>\n"
            "以下是与当前上下文语义相似的历史片段，可能存在身份关联：\n"
            + "\n\n".join(evidence_parts)
            + "\n</Vector_Evidence>"
        )


class DisambigContextProvider:
    """消歧上下文提供器

    为标注阶段提供别名消歧和活跃实体上下文。
    支持三级检索：
    - Level1: 别名表精确匹配
    - Level2: 活跃实体候选
    - Level3: 向量语义相似度检索（当前标注流程要求启用）

    同时提供图谱反馈能力：已裁决别名映射 + 已确认关系。
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
        self._novel_id = novel_id
        self._run_id = run_id
        self._lookback_chunks = lookback_chunks
        self._relations_cache: list[dict] | None = None
        self._level1_enabled = level1_enabled
        self._level2_enabled = level2_enabled
        self._level3_enabled = level3_enabled

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
        self._relations_cache = None

    def retrieve(
        self,
        alias: str,
        context_sentence: str | None = None,
        current_chunk: int | None = None,
    ) -> DisambigResult:
        """同步检索方法（Level 1 + Level 2）

        注意：Level 3 是异步操作，需要使用 retrieve_with_level3 方法。
        """
        logger.debug(f"DisambigContextProvider retrieve: alias='{alias}', chunk={current_chunk}")
        result = DisambigResult()

        if self._level1_enabled:
            canonical = self._alias_lookup.query(alias)
            if canonical:
                result.level1_hit = True
                result.canonical_name = canonical
                result.used_levels.append(1)
                logger.debug(f"DisambigContextProvider: Level1 hit, canonical='{canonical}'")
                return result

        if self._level2_enabled and current_chunk is not None:
            candidates = self._active_lookup.get_active_candidates(current_chunk, self._lookback_chunks)
            if candidates:
                result.level2_candidates = candidates
                result.used_levels.append(2)
                logger.debug(f"DisambigContextProvider: Level2 candidates={candidates[:5]}")

        if not result.used_levels:
            logger.debug(f"DisambigContextProvider: no levels used for alias='{alias}'")

        return result

    async def retrieve_with_level3(
        self,
        alias: str,
        context_sentence: str | None = None,
        current_chunk: int | None = None,
        exclude_chunk_ids: list[int] | None = None,
    ) -> DisambigResult:
        """异步检索方法（Level 1 + Level 2 + Level 3）"""
        result = self.retrieve(alias, context_sentence, current_chunk)

        if self._level3_enabled and not result.level1_hit and context_sentence:
            level3_results = await self._level3.search_similar_chunks(
                context_sentence,
                exclude_chunk_ids=exclude_chunk_ids,
            )
            if level3_results:
                result.level3_evidence = self._level3.format_evidence_for_prompt(level3_results)
                result.used_levels.append(3)
                logger.debug(f"DisambigContextProvider: Level3 found {len(level3_results)} similar chunks")

        return result

    def collect_evidence(
        self,
        names_in_chunk: list[str],
        current_chunk: int | None = None,
        context_text: str | None = None,
        exclude_chunk_ids: list[int] | None = None,
    ) -> EvidenceBundle:
        """
        收集三层证据，返回结构化 EvidenceBundle。

        创建时间: 2026-04-12
        创建者: TraeAI
        任务: 重构 DisambigContextProvider，实现证据收集方法
        说明: 同步版本，仅处理 Level 1 和 Level 2

        - structured_evidence: 来自 Level 1 的 alias 映射
        - local_evidence: 来自 Level 2 的活跃实体候选
        - semantic_evidence: 空（Level 3 需要异步调用）
        """
        structured_evidence: list[EvidenceItem] = []
        local_evidence: list[EvidenceItem] = []
        semantic_evidence: list[EvidenceItem] = []
        level2_candidates: list[str] = []

        if self._level2_enabled and current_chunk is not None:
            level2_candidates = self._active_lookup.get_active_candidates(current_chunk, self._lookback_chunks)
            if level2_candidates:
                logger.debug(f"collect_evidence: Level2 candidates={level2_candidates[:5]}")

        for name in names_in_chunk:
            canonical_name: str | None = None
            if self._level1_enabled:
                canonical_name = self._alias_lookup.query(name)

            if canonical_name:
                item = EvidenceItem(
                    evidence_type="alias_mapping",
                    source="level1",
                    content=f"{name} → {canonical_name}",
                    confidence=1.0,
                    metadata={"alias": name, "canonical": canonical_name},
                )
                structured_evidence.append(item)
                logger.debug(f"collect_evidence: Level1 hit, {name} → {canonical_name}")

            if level2_candidates:
                candidates_str = "、".join(level2_candidates[:5])
                item = EvidenceItem(
                    evidence_type="disambig_candidate",
                    source="level2",
                    content=f"「{name}」可能是：{candidates_str}",
                )
                local_evidence.append(item)
                logger.debug(f"collect_evidence: Level2 candidates for '{name}'")

        return EvidenceBundle(
            structured_evidence=structured_evidence,
            local_evidence=local_evidence,
            semantic_evidence=semantic_evidence,
        )

    async def collect_evidence_async(
        self,
        names_in_chunk: list[str],
        current_chunk: int | None = None,
        context_text: str | None = None,
        exclude_chunk_ids: list[int] | None = None,
    ) -> EvidenceBundle:
        """
        异步收集三层证据，返回结构化 EvidenceBundle。

        创建时间: 2026-04-12
        创建者: TraeAI
        任务: 重构 DisambigContextProvider，实现证据收集方法
        说明: 异步版本，处理 Level 1、Level 2 和 Level 3

        - structured_evidence: 来自 Level 1 的 alias 映射
        - local_evidence: 来自 Level 2 的活跃实体候选
        - semantic_evidence: 来自 Level 3 的语义相似片段
        """
        bundle = self.collect_evidence(
            names_in_chunk,
            current_chunk=current_chunk,
            context_text=context_text,
            exclude_chunk_ids=exclude_chunk_ids,
        )

        if self._level3_enabled and context_text and self.is_level3_available():
            level3_results = await self._level3.search_similar_chunks(
                context_text,
                exclude_chunk_ids=exclude_chunk_ids,
            )
            for r in level3_results:
                text = r.get("text", "")
                similarity = r.get("similarity", 0.0)
                chunk_id = r.get("chunk_id")
                if text:
                    item = EvidenceItem(
                        evidence_type="vector_evidence",
                        source="level3",
                        content=text,
                        score=similarity,
                        chunk_id=chunk_id,
                    )
                    bundle.semantic_evidence.append(item)

            if level3_results:
                logger.debug(f"collect_evidence_async: Level3 found {len(level3_results)} similar chunks")

        return bundle

    def is_level3_available(self) -> bool:
        """检查 Level 3 是否可用"""
        return self._level3_enabled and self._level3.is_available()

    def requires_level3(self) -> bool:
        """检查当前 provider 是否按当前流程配置要求启用 Level 3。"""
        return self._level3_enabled

    async def ensure_level3_ready(self) -> None:
        if self._level3_enabled:
            await self._level3.ensure_level3_ready()

    def build_disambig_context(
        self,
        names_in_chunk: list[str],
        current_chunk: int | None = None,
    ) -> str:
        """对 chunk 中出现的名字逐个执行层级检索，生成消歧线索文本。

        迁移说明:
        - 这是旧字符串链路的兼容接口
        - annotation 主链路应优先消费 collect_evidence() 返回的 EvidenceBundle
        - 新代码不应再以该 helper 作为主数据入口

        创建时间: 2025-03-12
        创建者: TraeAI
        任务: RAG 检索器实现

        修改时间: 2026-04-12
        修改者: TraeAI
        任务: 重构 DisambigContextProvider
        修改内容: 改为内部调用 collect_evidence() 并从 to_prompt_blocks() 派生

        - Level1 精确命中：直接追加到 alias_map，不生成额外线索
        - Level2 候选集：生成 <Disambig_Candidates> 供 LLM 参考
        - 未命中：不生成任何线索
        """
        if not names_in_chunk:
            return ""

        bundle = self.collect_evidence(names_in_chunk, current_chunk=current_chunk)
        blocks = bundle.to_prompt_blocks()
        return blocks.get("disambig_candidates", "")

    async def build_disambig_context_with_level3(
        self,
        names_in_chunk: list[str],
        current_chunk: int | None = None,
        context_text: str | None = None,
        exclude_chunk_ids: list[int] | None = None,
    ) -> str:
        """异步版本的 build_disambig_context，支持 Level 3

        迁移说明:
        - 这是旧字符串链路的兼容接口
        - annotation 主链路应优先消费 collect_evidence_async() 返回的 EvidenceBundle
        - 新代码不应再以该 helper 作为主数据入口

        创建时间: 2025-03-12
        创建者: TraeAI
        任务: RAG 检索器实现

        修改时间: 2026-04-12
        修改者: TraeAI
        任务: 重构 DisambigContextProvider
        修改内容: 改为内部调用 collect_evidence_async() 并从 to_prompt_blocks() 派生
        """
        if not names_in_chunk:
            return ""

        bundle = await self.collect_evidence_async(
            names_in_chunk,
            current_chunk=current_chunk,
            context_text=context_text,
            exclude_chunk_ids=exclude_chunk_ids,
        )
        blocks = bundle.to_prompt_blocks()

        disambig_candidates = blocks.get("disambig_candidates", "")
        vector_evidence = blocks.get("vector_evidence", "")

        if disambig_candidates and vector_evidence:
            return disambig_candidates + "\n\n" + vector_evidence
        return disambig_candidates or vector_evidence

    def build_graph_feedback_hint(
        self,
        existing_names: list[str],
        base_hint: str | None = None,
    ) -> str | None:
        """构建图谱反馈提示，包含已裁决别名映射和已确认关系。

        统一消歧阶段和标注阶段的图谱数据查询逻辑，
        替代散落在各处的直接 GraphRepository 调用。
        """
        if self._graph_repo is None or self._run_id is None:
            return base_hint

        existing_set = set(existing_names)
        parts: list[str] = []

        if base_hint:
            parts.append(base_hint)

        alias_map = self._alias_lookup.get_alias_map()
        graph_aliases = {a: c for a, c in alias_map.items() if a != c and c in existing_set}
        if graph_aliases:
            alias_lines = ["【图谱已裁决的别名映射】"]
            for alias, canonical in sorted(graph_aliases.items()):
                alias_lines.append(f"- {alias} → {canonical}")
            parts.append("\n".join(alias_lines))
            logger.debug(f"Graph feedback: injected {len(graph_aliases)} alias mappings")

        if self._relations_cache is None:
            self._relations_cache = self._graph_repo.fetch_current_relations(self._run_id, active_only=True)
        relations = self._relations_cache
        relevant_rels = [r for r in relations if r["from_name"] in existing_set or r["to_name"] in existing_set]
        if relevant_rels:
            rel_lines = ["【图谱已确认的关系】"]
            for r in relevant_rels[:10]:
                rel_lines.append(f"- {r['from_name']} ←{r['type']}→ {r['to_name']}")
            parts.append("\n".join(rel_lines))
            logger.debug(f"Graph feedback: injected {len(relevant_rels)} relations")

        if not parts:
            return base_hint

        return "\n".join(parts)
