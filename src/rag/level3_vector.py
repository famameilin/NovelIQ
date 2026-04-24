"""
RAG Level3 向量检索边界。

创建时间: 2026-04-23
任务: p1-rag-retriever-split
说明: 将向量可用性检查和语义检索逻辑从 provider 主类中拆出。
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from loguru import logger

from src.config import settings

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.models.local.embedding import EmbeddingClient
    from src.storage.repositories.chunk import SimilarChunkRow, SimilarParagraphRow


class Level3NotReadyError(RuntimeError):
    """Level 3 向量检索未就绪。"""


class Level3VectorEvidence:
    """
    Level3: 向量语义相似度检索。

    创建时间: 2026-04-23
    任务: p1-rag-retriever-split
    说明: 单独负责 Level3 readiness 检查与 chunk 检索，provider 只做编排。
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
        self._paragraph_rerank_available: bool | None = None

    def set_embedding_client(self, client: EmbeddingClient) -> None:
        """设置 Embedding 客户端。"""
        self._embedding_client = client
        self._available = None
        self._paragraph_rerank_available = None
        self._setup_checked = False

    def set_session(self, session: Session, run_id: str) -> None:
        """设置数据库会话与 run_id。"""
        self._session = session
        self._run_id = run_id
        self._available = None
        self._paragraph_rerank_available = None
        self._setup_checked = False

    async def ensure_level3_ready(self) -> None:
        """
        执行 Level3 readiness 检查。

        修改时间: 2026-04-24
        任务: level3-paragraph-readiness
        修改说明: paragraph rerank 已是 Level3 必需能力，启动检查必须同时校验 paragraph schema、数据存在与完整性。
        """
        if self._setup_checked:
            return
        if self._embedding_client is None or self._session is None or self._run_id is None:
            raise Level3NotReadyError("Level 3 requires embedding client, session, and run_id")

        actual_dim = await self._embedding_client.detect_embedding_dimension()
        if actual_dim != self._expected_embedding_dim:
            raise Level3NotReadyError(
                f"Level 3 embedding dimension mismatch: configured={self._expected_embedding_dim}, actual={actual_dim}"
            )

        from src.storage.repositories.chunk import (
            get_incomplete_paragraph_embedding_chunk_ids,
            get_missing_embedding_chunk_ids,
            has_embeddings,
            has_paragraph_embeddings,
        )
        from src.storage.vector_schema import validate_chunk_embeddings_schema, validate_paragraph_embeddings_schema

        try:
            validate_chunk_embeddings_schema(self._session, self._expected_embedding_dim)
        except ValueError as exc:
            raise Level3NotReadyError(str(exc)) from exc
        if not has_embeddings(self._session, self._run_id):
            raise Level3NotReadyError(f"Level 3 embeddings not found for run_id={self._run_id}")
        missing_chunk_embedding_ids = get_missing_embedding_chunk_ids(self._session, self._run_id)
        if missing_chunk_embedding_ids:
            preview_ids = missing_chunk_embedding_ids[:10]
            raise Level3NotReadyError(
                "Level 3 chunk embeddings incomplete for "
                f"run_id={self._run_id}, chunk_ids={preview_ids}, total={len(missing_chunk_embedding_ids)}"
            )

        try:
            validate_paragraph_embeddings_schema(self._session, self._expected_embedding_dim)
        except ValueError as exc:
            raise Level3NotReadyError(str(exc)) from exc
        if not has_paragraph_embeddings(self._session, self._run_id):
            raise Level3NotReadyError(f"Level 3 paragraph embeddings not found for run_id={self._run_id}")
        incomplete_chunk_ids = get_incomplete_paragraph_embedding_chunk_ids(self._session, self._run_id)
        if incomplete_chunk_ids:
            preview_ids = incomplete_chunk_ids[:10]
            raise Level3NotReadyError(
                "Level 3 paragraph embeddings incomplete for "
                f"run_id={self._run_id}, chunk_ids={preview_ids}, total={len(incomplete_chunk_ids)}"
            )

        self._available = True
        self._paragraph_rerank_available = True
        self._setup_checked = True
        logger.info("Level3 readiness passed with chunk and paragraph embeddings for run_id={}", self._run_id)

    def is_available(self) -> bool:
        """
        检查 Level3 是否可用。

        修改时间: 2026-04-24
        任务: fix-level3-availability-contract
        修改说明: 同步补齐 schema 校验，避免 `is_available()` 在表缺失或向量列维度不匹配时误报可用；
                  embedding 模型维度仍由 async readiness 入口做最终确认。
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

        from src.storage.repositories.chunk import (
            get_incomplete_paragraph_embedding_chunk_ids,
            get_missing_embedding_chunk_ids,
            has_embeddings,
            has_paragraph_embeddings,
        )
        from src.storage.vector_schema import validate_chunk_embeddings_schema, validate_paragraph_embeddings_schema

        try:
            validate_chunk_embeddings_schema(self._session, self._expected_embedding_dim)
            validate_paragraph_embeddings_schema(self._session, self._expected_embedding_dim)
        except ValueError as exc:
            self._available = False
            self._paragraph_rerank_available = False
            logger.debug("Level3VectorEvidence unavailable: schema validation failed: {}", exc)
            return False

        chunk_ready = has_embeddings(self._session, self._run_id)
        missing_chunk_embedding_ids = (
            get_missing_embedding_chunk_ids(self._session, self._run_id) if chunk_ready else []
        )
        paragraph_ready = has_paragraph_embeddings(self._session, self._run_id)
        incomplete_chunk_ids = (
            get_incomplete_paragraph_embedding_chunk_ids(self._session, self._run_id)
            if chunk_ready and not missing_chunk_embedding_ids and paragraph_ready
            else []
        )
        self._available = (
            chunk_ready and not missing_chunk_embedding_ids and paragraph_ready and not incomplete_chunk_ids
        )
        if self._available:
            self._paragraph_rerank_available = True
            logger.debug("Level3VectorEvidence: available, chunk and paragraph embeddings found in database")
        else:
            self._paragraph_rerank_available = False
            logger.debug(
                "Level3VectorEvidence unavailable: chunk_ready={} missing_chunk_embeddings={} "
                "paragraph_ready={} incomplete_paragraph_chunks={}",
                chunk_ready,
                missing_chunk_embedding_ids[:10],
                paragraph_ready,
                incomplete_chunk_ids[:10],
            )
        return self._available

    async def search_similar_chunks(
        self,
        query_text: str,
        exclude_chunk_ids: list[int] | None = None,
        max_chunk_id: int | None = None,
        top_k: int | None = None,
    ) -> list[SimilarChunkRow]:
        """
        检索语义相似的历史 chunk。

        创建时间: 2026-04-23
        任务: p1-rag-retriever-split
        说明: 保留原检索行为，但让 provider 不再直接处理向量层细节。

        修改时间: 2026-04-23
        任务: level3-history-cutoff
        修改说明: 透传 max_chunk_id 到 repository 层，统一约束 Level3 历史边界。

        修改时间: 2026-04-24
        任务: level3-paragraph-rerank
        修改说明: chunk 粗召回后，在命中 chunk_ids 内执行 paragraph rerank，并回填局部 evidence 预览。

        修改时间: 2026-04-24
        任务: level3-mention-rerank
        修改说明: 支持调用方传入 retrieval pool 大小，rerank 后再由 provider 裁剪 prompt 预算。
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

            effective_top_k = top_k or self._top_k
            results = search_similar_chunks(
                self._session,
                self._run_id,
                query_embedding,
                top_k=effective_top_k,
                similarity_threshold=self._similarity_threshold,
                exclude_chunk_ids=exclude_chunk_ids,
                max_chunk_id=max_chunk_id,
            )
            results = self._rerank_with_paragraphs(query_embedding, results, top_k=effective_top_k)
            logger.debug(
                "Level3VectorEvidence: found {} similar chunks for query (len={}) after paragraph rerank",
                len(results),
                len(query_text),
            )
            return results
        except Level3NotReadyError:
            raise
        except Exception as exc:
            logger.error("Level3VectorEvidence: search failed: {}", exc)
            return []

    def _is_paragraph_rerank_available(self) -> bool:
        """
        检查 paragraph rerank 数据是否可用。

        创建时间: 2026-04-24
        任务: level3-paragraph-rerank
        修改时间: 2026-04-24
        任务: level3-paragraph-readiness
        修改说明: paragraph rerank 不再是可选增强；缺失时抛出 readiness 错误。
        """
        if self._paragraph_rerank_available is not None:
            return self._paragraph_rerank_available
        if self._session is None or self._run_id is None:
            raise Level3NotReadyError("Level 3 paragraph rerank requires session and run_id")

        from src.storage.repositories.chunk import (
            get_incomplete_paragraph_embedding_chunk_ids,
            has_paragraph_embeddings,
        )
        from src.storage.vector_schema import validate_paragraph_embeddings_schema

        try:
            validate_paragraph_embeddings_schema(self._session, self._expected_embedding_dim)
        except ValueError as exc:
            raise Level3NotReadyError(str(exc)) from exc
        if not has_paragraph_embeddings(self._session, self._run_id):
            raise Level3NotReadyError(f"Level 3 paragraph embeddings not found for run_id={self._run_id}")
        incomplete_chunk_ids = get_incomplete_paragraph_embedding_chunk_ids(self._session, self._run_id)
        if incomplete_chunk_ids:
            raise Level3NotReadyError(
                "Level 3 paragraph embeddings incomplete for "
                f"run_id={self._run_id}, chunk_ids={incomplete_chunk_ids[:10]}, total={len(incomplete_chunk_ids)}"
            )

        self._paragraph_rerank_available = True
        return self._paragraph_rerank_available

    def _rerank_with_paragraphs(
        self,
        query_embedding: list[float],
        chunk_results: list[SimilarChunkRow],
        *,
        top_k: int,
    ) -> list[SimilarChunkRow]:
        """
        使用候选 chunk 内 paragraph 相似度重排 chunk 结果。

        创建时间: 2026-04-24
        任务: level3-paragraph-rerank
        说明: 只在 chunk 粗召回结果内查询 paragraph，避免全库 paragraph search 带来的噪声和时间边界风险。

        修改时间: 2026-04-24
        任务: level3-mention-rerank
        修改说明: 使用调用方指定的 retrieval pool 大小，而不是固定 prompt top_k。
        """
        if not chunk_results or self._session is None or self._run_id is None:
            return chunk_results
        if not self._is_paragraph_rerank_available():
            return chunk_results

        from src.storage.repositories.chunk import search_similar_paragraphs_within_chunks

        chunk_ids = [result.chunk_id for result in chunk_results]
        paragraph_results = search_similar_paragraphs_within_chunks(
            self._session,
            self._run_id,
            query_embedding,
            chunk_ids=chunk_ids,
            top_k=max(len(chunk_results) * 3, top_k),
            similarity_threshold=self._similarity_threshold,
        )
        if not paragraph_results:
            logger.info(
                "Level3 paragraph rerank found no paragraph matches; keeping chunk order chunk_candidates={}",
                len(chunk_results),
            )
            return chunk_results

        best_paragraph_by_chunk: dict[int, SimilarParagraphRow] = {}
        for paragraph in paragraph_results:
            existing = best_paragraph_by_chunk.get(paragraph.chunk_id)
            if existing is None or paragraph.similarity > existing.similarity:
                best_paragraph_by_chunk[paragraph.chunk_id] = paragraph

        reranked: list[SimilarChunkRow] = []
        for result in chunk_results:
            selected_paragraph = best_paragraph_by_chunk.get(result.chunk_id)
            if selected_paragraph is None:
                reranked.append(result)
                continue
            reranked.append(
                replace(
                    result,
                    similarity=selected_paragraph.similarity,
                    chunk_similarity=result.similarity,
                    local_preview=selected_paragraph.paragraph_text,
                    paragraph_index=selected_paragraph.paragraph_index,
                    paragraph_similarity=selected_paragraph.similarity,
                    paragraph_start_char=selected_paragraph.start_char,
                    paragraph_end_char=selected_paragraph.end_char,
                )
            )

        matched_count = sum(1 for result in reranked if result.local_preview)
        logger.info(
            "Level3 paragraph rerank applied: chunk_candidates={} paragraph_matches={} reranked_chunks={}",
            len(chunk_results),
            len(paragraph_results),
            matched_count,
        )
        return sorted(reranked, key=lambda item: item.similarity, reverse=True)[:top_k]
