"""
RAG Level3 段落向量检索边界

RAG 检索粒度固定为一个自然段：只做 run 级全库段落检索，
不再存在 chunk 级粗召回、paragraph 重排、mention 级召回等其它规格
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Never

from loguru import logger

from src.config import settings

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.models.local.embedding import EmbeddingClient
    from src.storage.repositories.chunk import SimilarParagraphRow


class Level3NotReadyError(RuntimeError):
    """Level 3 段落向量检索未就绪"""


class Level3VectorEvidence:
    """
    Level3: 自然段级向量语义相似度检索

    单独负责 Level3 readiness 检查与段落检索，provider 只做编排
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
        self._expected_embedding_dim = expected_embedding_dim or settings.models.paragraph_embedding.embedding_dim
        self._setup_checked = False

    def _raise_not_ready(self, message: str, *, cause: Exception | None = None) -> Never:
        """
        readiness 一旦发现 schema / 数据漂移，先清空缓存状态再抛错，
        避免后续 `is_available()` 继续复用过期的成功结果
        """
        self._available = False
        self._setup_checked = False
        if cause is None:
            raise Level3NotReadyError(message)
        raise Level3NotReadyError(message) from cause

    def set_embedding_client(self, client: EmbeddingClient) -> None:
        """设置 Embedding 客户端"""
        self._embedding_client = client
        self._available = None
        self._setup_checked = False

    def set_session(self, session: Session, run_id: str) -> None:
        """设置数据库会话与 run_id"""
        self._session = session
        self._run_id = run_id
        self._available = None
        self._setup_checked = False

    async def ensure_level3_ready(self) -> None:
        """
        执行 Level3 readiness 检查

        只校验 paragraph embedding：schema、数据存在与完整性
        """
        if self._embedding_client is None or self._session is None or self._run_id is None:
            self._raise_not_ready("Level 3 requires embedding client, session, and run_id")
        embedding_client = self._embedding_client
        session = self._session
        run_id = self._run_id

        actual_dim = await embedding_client.detect_embedding_dimension()
        if actual_dim != self._expected_embedding_dim:
            self._raise_not_ready(
                f"Level 3 embedding dimension mismatch: configured={self._expected_embedding_dim}, actual={actual_dim}"
            )

        from src.storage.repositories.chunk import (
            get_incomplete_paragraph_embedding_chunk_ids,
            has_paragraph_embeddings,
        )
        from src.storage.vector_schema import validate_paragraph_embeddings_schema

        try:
            validate_paragraph_embeddings_schema(session, self._expected_embedding_dim)
        except ValueError as exc:
            self._raise_not_ready(str(exc), cause=exc)
        if not has_paragraph_embeddings(session, run_id):
            self._raise_not_ready(f"Level 3 paragraph embeddings not found for run_id={run_id}")
        incomplete_chunk_ids = get_incomplete_paragraph_embedding_chunk_ids(session, run_id)
        if incomplete_chunk_ids:
            preview_ids = incomplete_chunk_ids[:10]
            self._raise_not_ready(
                "Level 3 paragraph embeddings incomplete for "
                f"run_id={run_id}, chunk_ids={preview_ids}, total={len(incomplete_chunk_ids)}"
            )

        self._available = True
        self._setup_checked = True
        logger.info("Level3 readiness passed with paragraph embeddings for run_id={}", self._run_id)

    def is_available(self) -> bool:
        """
        检查 Level3 是否可用
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
            has_paragraph_embeddings,
        )
        from src.storage.vector_schema import validate_paragraph_embeddings_schema

        try:
            validate_paragraph_embeddings_schema(self._session, self._expected_embedding_dim)
        except ValueError as exc:
            self._available = False
            logger.debug("Level3VectorEvidence unavailable: schema validation failed: {}", exc)
            return False

        paragraph_ready = has_paragraph_embeddings(self._session, self._run_id)
        incomplete_chunk_ids = (
            get_incomplete_paragraph_embedding_chunk_ids(self._session, self._run_id) if paragraph_ready else []
        )
        self._available = paragraph_ready and not incomplete_chunk_ids
        if self._available:
            logger.debug("Level3VectorEvidence: available, paragraph embeddings found in database")
        else:
            logger.debug(
                "Level3VectorEvidence unavailable: paragraph_ready={} incomplete_paragraph_chunks={}",
                paragraph_ready,
                incomplete_chunk_ids[:10],
            )
        return self._available

    async def search_similar_paragraphs(
        self,
        query_text: str,
        exclude_chunk_ids: list[int] | None = None,
        max_chunk_id: int | None = None,
        top_k: int | None = None,
        ensure_ready: bool = True,
    ) -> list[SimilarParagraphRow]:
        """
        检索语义相似的历史自然段

        证据单元就是一个自然段；支持 exclude_chunk_ids / max_chunk_id 历史边界
        """
        if ensure_ready:
            await self.ensure_level3_ready()
        elif self._available is not True:
            logger.debug("Level3VectorEvidence: cached readiness missing while ensure_ready=False")
            return []

        if self._available is not True and not self.is_available():
            return []
        if not query_text or not query_text.strip():
            logger.debug("Level3VectorEvidence: empty query text")
            return []
        if self._embedding_client is None or self._session is None or self._run_id is None:
            return []

        try:
            query_embedding = await self._embedding_client.get_embedding(query_text)
        except Level3NotReadyError:
            raise
        except Exception as exc:
            logger.error("Level3VectorEvidence: query embedding failed: {}", exc)
            return []

        if not query_embedding:
            logger.warning("Level3VectorEvidence: failed to get query embedding")
            return []

        try:
            effective_top_k = top_k or self._top_k
            results = self._search_paragraphs_by_embedding(
                query_embedding,
                exclude_chunk_ids=exclude_chunk_ids,
                max_chunk_id=max_chunk_id,
                top_k=effective_top_k,
            )
            logger.debug(
                "Level3VectorEvidence: found {} similar paragraphs for query (len={})",
                len(results),
                len(query_text),
            )
            return results
        except Level3NotReadyError:
            raise
        except Exception as exc:
            logger.error("Level3VectorEvidence: search failed: {}", exc)
            return []

    async def search_similar_paragraphs_many(
        self,
        query_texts: list[str],
        exclude_chunk_ids: list[int] | None = None,
        max_chunk_id: int | None = None,
        top_k: int | None = None,
        ensure_ready: bool = True,
    ) -> list[list[SimilarParagraphRow]]:
        """
        多 query 场景先批量生成 embedding，再逐条执行 run-scoped 段落检索
        """
        if not query_texts:
            return []

        if ensure_ready:
            await self.ensure_level3_ready()
        elif self._available is not True:
            logger.debug("Level3VectorEvidence: cached readiness missing while ensure_ready=False for batched queries")
            return [[] for _ in query_texts]

        if self._available is not True and not self.is_available():
            return [[] for _ in query_texts]
        if self._embedding_client is None or self._session is None or self._run_id is None:
            return [[] for _ in query_texts]

        normalized_queries = [query_text.strip() for query_text in query_texts]
        if not any(normalized_queries):
            return [[] for _ in query_texts]

        try:
            query_embeddings = await self._embedding_client.embed_texts(query_texts)
        except Level3NotReadyError:
            raise
        except Exception as exc:
            logger.warning(
                "Level3VectorEvidence: batched embedding failed, fallback to isolated queries: {}",
                exc,
            )
            return await self._search_paragraphs_many_isolated(
                query_texts,
                exclude_chunk_ids=exclude_chunk_ids,
                max_chunk_id=max_chunk_id,
                top_k=top_k,
            )

        try:
            effective_top_k = top_k or self._top_k
            results_by_query: list[list[SimilarParagraphRow]] = []
            for normalized_query, query_embedding in zip(normalized_queries, query_embeddings, strict=True):
                if not normalized_query or not query_embedding:
                    results_by_query.append([])
                    continue
                try:
                    results_by_query.append(
                        self._search_paragraphs_by_embedding(
                            query_embedding,
                            exclude_chunk_ids=exclude_chunk_ids,
                            max_chunk_id=max_chunk_id,
                            top_k=effective_top_k,
                        )
                    )
                except Level3NotReadyError:
                    raise
                except Exception as exc:
                    logger.error(
                        "Level3VectorEvidence: isolated batched query search failed query_len={} error={}",
                        len(normalized_query),
                        exc,
                    )
                    results_by_query.append([])
            logger.debug(
                "Level3VectorEvidence: batched query search complete query_count={} top_k={}",
                len(query_texts),
                effective_top_k,
            )
            return results_by_query
        except Level3NotReadyError:
            raise
        except Exception as exc:
            logger.error("Level3VectorEvidence: batched search failed: {}", exc)
            return [[] for _ in query_texts]

    async def _search_paragraphs_many_isolated(
        self,
        query_texts: list[str],
        *,
        exclude_chunk_ids: list[int] | None,
        max_chunk_id: int | None,
        top_k: int | None,
    ) -> list[list[SimilarParagraphRow]]:
        """
        batched 路径出错时逐 query 回退
        """
        results_by_query: list[list[SimilarParagraphRow]] = []
        for query_text in query_texts:
            normalized_query = query_text.strip()
            if not normalized_query:
                results_by_query.append([])
                continue
            query_results = await self.search_similar_paragraphs(
                query_text,
                exclude_chunk_ids=exclude_chunk_ids,
                max_chunk_id=max_chunk_id,
                top_k=top_k,
                ensure_ready=False,
            )
            results_by_query.append(query_results)
        return results_by_query

    def _search_paragraphs_by_embedding(
        self,
        query_embedding: list[float],
        *,
        exclude_chunk_ids: list[int] | None,
        max_chunk_id: int | None,
        top_k: int,
    ) -> list[SimilarParagraphRow]:
        """
        复用 precomputed query embedding 的自然段检索
        """
        from src.storage.repositories.chunk import search_similar_paragraphs

        session = self._session
        run_id = self._run_id
        if session is None or run_id is None:
            self._raise_not_ready("Level 3 search requires session and run_id")

        return search_similar_paragraphs(
            session,
            run_id,
            query_embedding,
            top_k=top_k,
            similarity_threshold=self._similarity_threshold,
            exclude_chunk_ids=exclude_chunk_ids,
            max_chunk_id=max_chunk_id,
        )
