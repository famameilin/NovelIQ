from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import numpy as np
from loguru import logger

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
- Level1ExactMatch 使用 EntityRepository 接口
- Level3VectorEvidence 使用 EntityRepository 接口
- 添加 run_id 参数支持
"""

if TYPE_CHECKING:
    import networkx as nx
    from src.models.local.embedding import EmbeddingClient
    from src.storage.repositories import EntityRepository


@dataclass
class RAGResult:
    level1_hit: bool = False
    level2_candidates: List[str] = field(default_factory=list)
    level3_evidence: List[str] = field(default_factory=list)
    canonical_name: Optional[str] = None
    used_levels: List[int] = field(default_factory=list)


class Level1ExactMatch:
    def __init__(
        self,
        entity_repo: "EntityRepository",
        novel_id: str = "default",
        run_id: str | None = None,
    ):
        self._entity_repo = entity_repo
        self._novel_id = novel_id
        self._run_id = run_id

    def query(self, alias: str) -> Optional[str]:
        entity = self._entity_repo.fetch_entity_by_alias(
            self._novel_id,
            alias,
            self._run_id,
        )
        if entity:
            canonical = entity.get("canonical")
            logger.debug(f"Level1 exact match: '{alias}' -> '{canonical}'")
            return canonical
        return None

    def get_all_known_aliases(self) -> Dict[str, str]:
        alias_rows = self._entity_repo.fetch_all_aliases_with_canonical(
            self._novel_id,
            self._run_id,
        )
        alias_map = {}
        for row in alias_rows:
            canonical, alias = row
            alias_map[canonical] = canonical
            alias_map[alias] = canonical
        return alias_map


class Level2GraphConstraint:
    def __init__(self, G: Optional["nx.Graph"] = None):
        self._graph = G

    def set_graph(self, G: "nx.Graph") -> None:
        self._graph = G

    def get_active_candidates(
        self,
        current_chunk: int,
        lookback: int = 10,
    ) -> List[str]:
        if self._graph is None:
            return []

        start_chunk = max(0, current_chunk - lookback)
        candidates = []

        for node, attrs in self._graph.nodes(data=True):
            active_chunks = attrs.get("active_chunks", [])
            last_seen = attrs.get("last_seen")

            if last_seen and start_chunk <= last_seen <= current_chunk:
                candidates.append(node)
            elif active_chunks:
                for chunk_id in active_chunks:
                    if start_chunk <= chunk_id <= current_chunk:
                        candidates.append(node)
                        break

        logger.debug(f"Level2 graph constraint: {len(candidates)} active candidates")
        return candidates

    def get_node_aliases(self, node_name: str) -> List[str]:
        if self._graph is None or node_name not in self._graph.nodes:
            return []
        return self._graph.nodes[node_name].get("aliases", [])

    def get_all_known_aliases(self) -> Dict[str, str]:
        if self._graph is None:
            return {}

        alias_map = {}
        for node, attrs in self._graph.nodes(data=True):
            canonical = attrs.get("canonical_name", node)
            alias_map[canonical] = canonical
            for alias in attrs.get("aliases", []):
                alias_map[alias] = canonical
        return alias_map


class Level3VectorEvidence:
    def __init__(
        self,
        entity_repo: "EntityRepository",
        novel_id: str = "default",
        run_id: str | None = None,
        embedding_client: Optional["EmbeddingClient"] = None,
        similarity_threshold: float = 0.7,
        top_k: int = 3,
    ):
        self._entity_repo = entity_repo
        self._novel_id = novel_id
        self._run_id = run_id
        self._embedding_client = embedding_client
        self._similarity_threshold = similarity_threshold
        self._top_k = top_k
        self._available = embedding_client is not None

    def set_embedding_client(self, client: "EmbeddingClient") -> None:
        self._embedding_client = client
        self._available = True

    def is_available(self) -> bool:
        return self._available and self._embedding_client is not None

    def search_similar_entities(
        self,
        query_text: str,
    ) -> List[Dict[str, Any]]:
        if not self.is_available():
            return []

        try:
            query_vec = self._embedding_client.get_embedding(query_text) if self._embedding_client else None
        except Exception as e:
            logger.warning(f"Level3 embedding failed: {e}")
            self._available = False
            return []

        if query_vec is None:
            return []

        entity_rows = self._entity_repo.fetch_entities_with_embeddings(
            self._novel_id,
            self._run_id,
        )

        results: List[Dict[str, Any]] = []
        for row in entity_rows:
            entity_id, canonical, description, embedding_blob = row
            if embedding_blob is None:
                continue
            entity_vec = pickle.loads(embedding_blob)

            similarity = self._compute_similarity(query_vec, entity_vec)
            if similarity >= self._similarity_threshold:
                results.append(
                    {
                        "entity_id": entity_id,
                        "canonical": canonical,
                        "description": description,
                        "similarity": similarity,
                    }
                )

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[: self._top_k]

    def _compute_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        arr1 = np.array(vec1)
        arr2 = np.array(vec2)
        dot_product = np.dot(arr1, arr2)
        norm1 = np.linalg.norm(arr1)
        norm2 = np.linalg.norm(arr2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(dot_product / (norm1 * norm2))


class RAGRetriever:
    def __init__(
        self,
        entity_repo: "EntityRepository",
        novel_id: str = "default",
        run_id: str | None = None,
        graph: Optional["nx.Graph"] = None,
        embedding_client: Optional["EmbeddingClient"] = None,
        similarity_threshold: float = 0.7,
        lookback_chunks: int = 10,
    ):
        self._level1 = Level1ExactMatch(entity_repo, novel_id, run_id)
        self._level2 = Level2GraphConstraint(graph)
        self._level3 = Level3VectorEvidence(
            entity_repo,
            novel_id,
            run_id,
            embedding_client,
            similarity_threshold,
        )
        self._novel_id = novel_id
        self._run_id = run_id
        self._lookback_chunks = lookback_chunks

    def set_graph(self, graph: "nx.Graph") -> None:
        self._level2.set_graph(graph)

    def set_embedding_client(self, client: "EmbeddingClient") -> None:
        self._level3.set_embedding_client(client)

    def retrieve(
        self,
        alias: str,
        context_sentence: Optional[str] = None,
        current_chunk: Optional[int] = None,
    ) -> RAGResult:
        logger.debug(f"RAG retrieve: alias='{alias}', chunk={current_chunk}")
        result = RAGResult()

        canonical = self._level1.query(alias)
        if canonical:
            result.level1_hit = True
            result.canonical_name = canonical
            result.used_levels.append(1)
            logger.debug(f"RAG result: Level1 hit, canonical='{canonical}'")
            return result

        if current_chunk is not None:
            candidates = self._level2.get_active_candidates(current_chunk, self._lookback_chunks)
            if candidates:
                result.level2_candidates = candidates
                result.used_levels.append(2)
                logger.debug(f"RAG result: Level2 candidates={candidates[:5]}")

        if context_sentence and self._level3.is_available():
            evidence = self._level3.search_similar_entities(context_sentence)
            if evidence:
                result.level3_evidence = [f"{e['canonical']}: {e['description']}" for e in evidence]
                result.used_levels.append(3)
                logger.debug(f"RAG result: Level3 evidence count={len(evidence)}")

        if not result.used_levels:
            logger.debug(f"RAG result: no levels used for alias='{alias}'")

        return result

    def get_known_aliases(self) -> Dict[str, str]:
        aliases = self._level1.get_all_known_aliases()
        if not aliases:
            aliases = self._level2.get_all_known_aliases()
        return aliases

    def format_for_prompt(self, result: RAGResult) -> str:
        parts = []

        if result.level2_candidates:
            candidates_str = "、".join(result.level2_candidates[:5])
            parts.append(f"<Alias_Candidates>{candidates_str}</Alias_Candidates>")

        if result.level3_evidence:
            evidence_str = "\n".join(result.level3_evidence[:3])
            parts.append(f"<Evidence>\n{evidence_str}\n</Evidence>")

        return "\n".join(parts)

    def format_known_aliases_for_prompt(self) -> str:
        aliases = self.get_known_aliases()
        if not aliases:
            return ""

        alias_pairs = [f"{alias} → {canonical}" for alias, canonical in sorted(aliases.items())[:20]]
        return f"<Known_Aliases>\n{chr(10).join(alias_pairs)}\n</Known_Aliases>"
