from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

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
    from src.models.local.embedding import EmbeddingClient
    from src.storage.repositories import EntityRepository, GraphRepository



@dataclass
class RAGResult:
    level1_hit: bool = False
    level2_candidates: list[str] = field(default_factory=list)
    level3_evidence: list[str] = field(default_factory=list)
    canonical_name: str | None = None
    used_levels: list[int] = field(default_factory=list)


class Level1ExactMatch:
    def __init__(
        self,
        graph_repo: GraphRepository | None = None,
        entity_repo: EntityRepository | None = None,
        novel_id: str = "default",
        run_id: str | None = None,
    ):
        self._graph_repo = graph_repo
        self._entity_repo = entity_repo
        self._novel_id = novel_id
        self._run_id = run_id

    def query(self, alias: str) -> str | None:
        if self._graph_repo is None or self._run_id is None:
            return None
        canonical = self._graph_repo.fetch_alias_map(self._run_id).get(alias)
        if canonical:
            logger.debug(f"Level1 exact match(graph): '{alias}' -> '{canonical}'")
        return canonical

    def get_all_known_aliases(self) -> dict[str, str]:
        if self._graph_repo is None or self._run_id is None:
            return {}
        return self._graph_repo.fetch_alias_map(self._run_id)



class Level2GraphConstraint:
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

    def get_all_known_aliases(self) -> dict[str, str]:
        if self._graph_repo is None or self._run_id is None:
            return {}
        return self._graph_repo.fetch_alias_map(self._run_id)



class Level3VectorEvidence:
    def __init__(
        self,
        entity_repo: EntityRepository,
        novel_id: str = "default",
        run_id: str | None = None,
        embedding_client: EmbeddingClient | None = None,
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

    def set_embedding_client(self, client: EmbeddingClient) -> None:
        self._embedding_client = client
        self._available = True

    def is_available(self) -> bool:
        return self._available and self._embedding_client is not None

    def search_similar_entities(
        self,
        query_text: str,
    ) -> list[dict[str, Any]]:
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

        results: list[dict[str, Any]] = []
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

    def _compute_similarity(self, vec1: list[float], vec2: list[float]) -> float:
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
        entity_repo: EntityRepository,
        novel_id: str = "default",
        run_id: str | None = None,
        graph_repo: GraphRepository | None = None,
        embedding_client: EmbeddingClient | None = None,
        similarity_threshold: float = 0.7,
        lookback_chunks: int = 10,
    ):

        self._level1 = Level1ExactMatch(
            graph_repo=graph_repo,
            entity_repo=entity_repo,
            novel_id=novel_id,
            run_id=run_id,
        )
        self._level2 = Level2GraphConstraint(graph_repo=graph_repo, run_id=run_id)

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



    def set_embedding_client(self, client: EmbeddingClient) -> None:
        self._level3.set_embedding_client(client)

    def retrieve(
        self,
        alias: str,
        context_sentence: str | None = None,
        current_chunk: int | None = None,
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

    def get_known_aliases(self) -> dict[str, str]:
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
