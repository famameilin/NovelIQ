"""
创建时间: 2026-04-10
创建者: TraeAI
任务: implement-level3-vector-retrieval
说明: Level 3 向量检索单元测试

测试覆盖：
- ChunkEmbedding ORM 模型
- 向量存储与检索功能
- Level3VectorEvidence 可用性检查
- NarrativeEvidenceService Level 3 集成
- 共享 evidence renderer 边界回归
"""

import inspect
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import settings
from src.knowledge.authority.types import ActiveEntityContext
from src.models.local.evidence_renderer_shared import (
    render_disambig_candidates,
    render_emotion_exemplars,
    render_vector_evidence,
)
from src.rag.evidence_types import EvidenceBundle, EvidenceItem
from src.rag.evidence_contracts import EvidenceRequest
from src.rag.retriever import NarrativeEvidenceService, Level3NotReadyError, Level3VectorEvidence
from src.storage.repositories.chunk import SimilarChunkRow, SimilarParagraphRow


def _build_evidence_request(
    *,
    consumer: str = "incremental_disambiguation",
    objective: str = "identity",
    query_text: str = "",
    requested_names: list[str] | None = None,
    seed_entities: list[str] | None = None,
    background_entities: list[str] | None = None,
    current_chunk: int | None = None,
    max_chunk_id: int | None = None,
    exclude_chunk_ids: list[int] | None = None,
    need_level1: bool = True,
    need_level2: bool = True,
    need_level3: bool = False,
    allow_llm_query_expansion: bool = False,
) -> EvidenceRequest:
    """
    创建时间: 2026-04-25
    任务: evidence-service-request-unification
    说明: 统一生成 NarrativeEvidenceService.collect() 可消费的显式 request，
          避免各测试继续散落着旧 provider 的弱语义调用方式。
    """

    normalized_requested = requested_names or list(seed_entities or [])
    normalized_seed = seed_entities or []
    return EvidenceRequest(
        consumer=consumer,
        objective=objective,  # type: ignore[arg-type]
        query_text=query_text,
        requested_names=normalized_requested,
        seed_entities=normalized_seed,
        background_entities=background_entities or [],
        current_chunk=current_chunk,
        max_chunk_id=max_chunk_id,
        exclude_chunk_ids=exclude_chunk_ids or ([] if current_chunk is None else [current_chunk]),
        need_level1=need_level1,
        need_level2=need_level2,
        need_level3=need_level3,
        allow_llm_query_expansion=allow_llm_query_expansion,
        top_k=settings.rag.level3_top_k,
        max_queries=settings.rag.level3_max_queries,
        model_rerank_query_max_chars=settings.rag.level3_model_rerank_query_max_chars,
    )


class TestLevel3VectorEvidence(unittest.TestCase):
    """Level3VectorEvidence 单元测试"""

    def test_is_available_no_embedding_client(self) -> None:
        """没有 EmbeddingClient 时不可用"""
        level3 = Level3VectorEvidence()
        self.assertFalse(level3.is_available())

    def test_is_available_no_session(self) -> None:
        """没有 session 时不可用"""
        mock_client = MagicMock()
        level3 = Level3VectorEvidence(embedding_client=mock_client)
        self.assertFalse(level3.is_available())

    def test_is_available_no_run_id(self) -> None:
        """没有 run_id 时不可用"""
        mock_client = MagicMock()
        mock_session = MagicMock()
        level3 = Level3VectorEvidence(
            session=mock_session,
            embedding_client=mock_client,
        )
        self.assertFalse(level3.is_available())

    @patch("src.storage.repositories.chunk.has_paragraph_embeddings", return_value=True)
    @patch("src.storage.repositories.chunk.has_embeddings", return_value=False)
    def test_is_available_no_embeddings_in_db(self, mock_has: MagicMock, mock_has_paragraph: MagicMock) -> None:
        """数据库没有 embedding 数据时不可用"""
        mock_client = MagicMock()
        mock_session = MagicMock()

        level3 = Level3VectorEvidence(
            session=mock_session,
            run_id="test-run-id",
            embedding_client=mock_client,
        )
        with (
            patch("src.storage.vector_schema.validate_chunk_embeddings_schema"),
            patch("src.storage.vector_schema.validate_paragraph_embeddings_schema"),
        ):
            self.assertFalse(level3.is_available())

    @patch("src.storage.repositories.chunk.has_paragraph_embeddings", return_value=False)
    @patch("src.storage.repositories.chunk.has_embeddings", return_value=True)
    def test_is_available_no_paragraph_embeddings_in_db(
        self,
        mock_has: MagicMock,
        mock_has_paragraph: MagicMock,
    ) -> None:
        """
        创建时间: 2026-04-24
        任务: level3-paragraph-readiness
        说明: paragraph rerank 是 Level3 必需能力，缺少 paragraph embeddings 时不可用。
        """
        mock_client = MagicMock()
        mock_session = MagicMock()

        level3 = Level3VectorEvidence(
            session=mock_session,
            run_id="test-run-id",
            embedding_client=mock_client,
        )
        with (
            patch("src.storage.vector_schema.validate_chunk_embeddings_schema"),
            patch("src.storage.vector_schema.validate_paragraph_embeddings_schema"),
        ):
            self.assertFalse(level3.is_available())

    @patch("src.storage.repositories.chunk.get_incomplete_paragraph_embedding_chunk_ids", return_value=[3])
    @patch("src.storage.repositories.chunk.get_missing_embedding_chunk_ids", return_value=[])
    @patch("src.storage.repositories.chunk.has_paragraph_embeddings", return_value=True)
    @patch("src.storage.repositories.chunk.has_embeddings", return_value=True)
    def test_is_available_false_when_paragraph_embeddings_incomplete(
        self,
        mock_has: MagicMock,
        mock_has_paragraph: MagicMock,
        mock_missing: MagicMock,
        mock_incomplete: MagicMock,
    ) -> None:
        """
        创建时间: 2026-04-24
        任务: level3-paragraph-readiness
        说明: 某些 chunk 缺少 paragraph embedding 时，Level3 不应报告可用。
        """
        mock_client = MagicMock()
        mock_session = MagicMock()

        level3 = Level3VectorEvidence(
            session=mock_session,
            run_id="test-run-id",
            embedding_client=mock_client,
        )
        with (
            patch("src.storage.vector_schema.validate_chunk_embeddings_schema"),
            patch("src.storage.vector_schema.validate_paragraph_embeddings_schema"),
        ):
            self.assertFalse(level3.is_available())

    @patch("src.storage.repositories.chunk.get_missing_embedding_chunk_ids", return_value=[5])
    @patch("src.storage.repositories.chunk.has_paragraph_embeddings", return_value=True)
    @patch("src.storage.repositories.chunk.has_embeddings", return_value=True)
    def test_is_available_false_when_chunk_embeddings_incomplete(
        self,
        mock_has: MagicMock,
        mock_has_paragraph: MagicMock,
        mock_missing: MagicMock,
    ) -> None:
        """
        创建时间: 2026-04-24
        任务: fix-level3-embedding-partial-write
        说明: chunk embedding 是粗召回边界，任一 chunk 缺失时 Level3 不应报告可用。
        """
        mock_client = MagicMock()
        mock_session = MagicMock()

        level3 = Level3VectorEvidence(
            session=mock_session,
            run_id="test-run-id",
            embedding_client=mock_client,
        )
        with (
            patch("src.storage.vector_schema.validate_chunk_embeddings_schema"),
            patch("src.storage.vector_schema.validate_paragraph_embeddings_schema"),
        ):
            self.assertFalse(level3.is_available())

    @patch("src.storage.repositories.chunk.get_incomplete_paragraph_embedding_chunk_ids", return_value=[])
    @patch("src.storage.repositories.chunk.get_missing_embedding_chunk_ids", return_value=[])
    @patch("src.storage.repositories.chunk.has_paragraph_embeddings", return_value=True)
    @patch("src.storage.repositories.chunk.has_embeddings", return_value=True)
    def test_is_available_success(
        self,
        mock_has: MagicMock,
        mock_has_paragraph: MagicMock,
        mock_missing: MagicMock,
        mock_incomplete: MagicMock,
    ) -> None:
        """所有条件满足时可用"""
        mock_client = MagicMock()
        mock_session = MagicMock()

        level3 = Level3VectorEvidence(
            session=mock_session,
            run_id="test-run-id",
            embedding_client=mock_client,
        )
        with (
            patch("src.storage.vector_schema.validate_chunk_embeddings_schema"),
            patch("src.storage.vector_schema.validate_paragraph_embeddings_schema"),
        ):
            self.assertTrue(level3.is_available())

    def test_search_similar_chunks_by_embedding_requires_runtime_state(self) -> None:
        """
        创建时间: 2026-04-25
        任务: fix-level3-typecheck-regressions
        说明: 预计算 embedding 的 helper 不能只依赖外层调用者兜底；缺少 session/run_id 时应立即报错。
        """
        level3 = Level3VectorEvidence()

        with self.assertRaisesRegex(Level3NotReadyError, "requires session and run_id"):
            level3._search_similar_chunks_by_embedding(
                [0.1] * settings.models.semantic_chunking.embedding_dim,
                exclude_chunk_ids=None,
                max_chunk_id=None,
                top_k=5,
            )

class TestLevel3VectorEvidenceAsync:
    """Level3VectorEvidence 异步测试"""

    @pytest.mark.asyncio
    @patch("src.storage.repositories.chunk.search_similar_chunks")
    async def test_search_similar_chunks_success(self, mock_search: MagicMock) -> None:
        """成功检索相似 chunk"""
        mock_client = MagicMock()
        mock_client.detect_embedding_dimension = AsyncMock(return_value=settings.models.semantic_chunking.embedding_dim)
        mock_client.get_embedding = AsyncMock(return_value=[0.1] * settings.models.semantic_chunking.embedding_dim)
        mock_session = MagicMock()

        mock_search.return_value = [
            SimilarChunkRow(chunk_id=1, text="相似文本", similarity=0.9, emotional_valence="mild_negative"),
        ]

        with (
            patch("src.storage.repositories.chunk.has_embeddings", return_value=True),
            patch("src.storage.repositories.chunk.get_missing_embedding_chunk_ids", return_value=[]),
            patch("src.storage.repositories.chunk.has_paragraph_embeddings", return_value=True),
            patch("src.storage.repositories.chunk.get_incomplete_paragraph_embedding_chunk_ids", return_value=[]),
            patch("src.storage.repositories.chunk.search_similar_paragraphs_within_chunks", return_value=[]),
            patch("src.storage.vector_schema.validate_chunk_embeddings_schema"),
            patch("src.storage.vector_schema.validate_paragraph_embeddings_schema"),
        ):
            level3 = Level3VectorEvidence(
                session=mock_session,
                run_id="test-run-id",
                embedding_client=mock_client,
            )
            results = await level3.search_similar_chunks("查询文本", max_chunk_id=7)

        assert len(results) == 1
        assert results[0].chunk_id == 1
        assert results[0].emotional_valence == "mild_negative"
        assert mock_search.call_args.kwargs["max_chunk_id"] == 7
        assert mock_client.detect_embedding_dimension.await_count == 1

    @pytest.mark.asyncio
    @patch("src.storage.repositories.chunk.search_similar_paragraphs_within_chunks")
    @patch("src.storage.repositories.chunk.search_similar_chunks")
    async def test_search_similar_chunks_reranks_with_candidate_chunk_paragraphs(
        self,
        mock_search_chunks: MagicMock,
        mock_search_paragraphs: MagicMock,
    ) -> None:
        """
        创建时间: 2026-04-24
        任务: level3-paragraph-rerank
        说明: Level3 应先粗召回 chunk，再仅在命中 chunk_ids 内使用 paragraph embedding 回填局部 evidence。
        """
        mock_client = MagicMock()
        mock_client.detect_embedding_dimension = AsyncMock(return_value=settings.models.semantic_chunking.embedding_dim)
        mock_client.get_embedding = AsyncMock(return_value=[0.1] * settings.models.semantic_chunking.embedding_dim)
        mock_session = MagicMock()

        mock_search_chunks.return_value = [
            SimilarChunkRow(chunk_id=1, text="chunk-1 full text", similarity=0.82),
            SimilarChunkRow(chunk_id=2, text="chunk-2 full text", similarity=0.81),
        ]
        mock_search_paragraphs.return_value = [
            SimilarParagraphRow(
                chunk_id=2,
                paragraph_index=1,
                paragraph_text="灰衣人站在门外。",
                local_start_char=5,
                local_end_char=13,
                global_start_char=205,
                global_end_char=213,
                similarity=0.96,
            ),
            SimilarParagraphRow(
                chunk_id=1,
                paragraph_index=0,
                paragraph_text="普通场景。",
                local_start_char=0,
                local_end_char=5,
                global_start_char=100,
                global_end_char=105,
                similarity=0.90,
            ),
        ]

        with (
            patch("src.storage.repositories.chunk.has_embeddings", return_value=True),
            patch("src.storage.repositories.chunk.get_missing_embedding_chunk_ids", return_value=[]),
            patch("src.storage.repositories.chunk.has_paragraph_embeddings", return_value=True),
            patch("src.storage.repositories.chunk.get_incomplete_paragraph_embedding_chunk_ids", return_value=[]),
            patch("src.storage.vector_schema.validate_chunk_embeddings_schema"),
            patch("src.storage.vector_schema.validate_paragraph_embeddings_schema"),
        ):
            level3 = Level3VectorEvidence(
                session=mock_session,
                run_id="test-run-id",
                embedding_client=mock_client,
                top_k=2,
            )
            results = await level3.search_similar_chunks("灰衣人是谁")

        assert [row.chunk_id for row in results] == [2, 1]
        assert results[0].local_preview == "灰衣人站在门外。"
        assert results[0].paragraph_index == 1
        assert results[0].chunk_semantic_score == 0.81
        assert results[0].similarity == 0.96
        assert results[0].paragraph_semantic_score == 0.96
        assert results[0].final_rank_score == 0.96
        assert mock_search_paragraphs.call_args.kwargs["chunk_ids"] == [1, 2]

    @pytest.mark.asyncio
    @patch("src.storage.repositories.chunk.search_similar_paragraphs_within_chunks", return_value=[])
    @patch("src.storage.repositories.chunk.search_similar_chunks")
    async def test_search_similar_chunks_keeps_chunk_order_when_no_paragraph_match(
        self,
        mock_search_chunks: MagicMock,
        mock_search_paragraphs: MagicMock,
    ) -> None:
        """
        创建时间: 2026-04-24
        任务: level3-paragraph-readiness
        说明: paragraph 数据完整但当前 query 没有 paragraph 命中时，应保留 chunk 粗召回结果，而不是静默丢证据。
        """
        mock_client = MagicMock()
        mock_client.detect_embedding_dimension = AsyncMock(return_value=settings.models.semantic_chunking.embedding_dim)
        mock_client.get_embedding = AsyncMock(return_value=[0.1] * settings.models.semantic_chunking.embedding_dim)
        mock_session = MagicMock()
        mock_search_chunks.return_value = [
            SimilarChunkRow(chunk_id=1, text="chunk-1 full text", similarity=0.82),
            SimilarChunkRow(chunk_id=2, text="chunk-2 full text", similarity=0.81),
        ]

        with (
            patch("src.storage.repositories.chunk.has_embeddings", return_value=True),
            patch("src.storage.repositories.chunk.get_missing_embedding_chunk_ids", return_value=[]),
            patch("src.storage.repositories.chunk.has_paragraph_embeddings", return_value=True),
            patch("src.storage.repositories.chunk.get_incomplete_paragraph_embedding_chunk_ids", return_value=[]),
            patch("src.storage.vector_schema.validate_chunk_embeddings_schema"),
            patch("src.storage.vector_schema.validate_paragraph_embeddings_schema"),
        ):
            level3 = Level3VectorEvidence(
                session=mock_session,
                run_id="test-run-id",
                embedding_client=mock_client,
                top_k=2,
            )
            results = await level3.search_similar_chunks("没有局部命中的 query")

        assert [row.chunk_id for row in results] == [1, 2]
        assert all(row.local_preview is None for row in results)

    @pytest.mark.asyncio
    @patch("src.storage.repositories.chunk.search_similar_paragraphs_within_chunks", return_value=[])
    @patch("src.storage.repositories.chunk.search_similar_chunks")
    async def test_search_similar_chunks_reuses_cached_readiness_when_caller_already_ensured(
        self,
        mock_search_chunks: MagicMock,
        mock_search_paragraphs: MagicMock,
    ) -> None:
        """
        创建时间: 2026-04-24
        任务: fix-level3-query-readiness-duplication
        说明: 外层已完成 readiness 时，后续多次 Level3 query 不应重复探测 embedding 维度或重跑完整性检查。
        """
        mock_client = MagicMock()
        mock_client.detect_embedding_dimension = AsyncMock(return_value=settings.models.semantic_chunking.embedding_dim)
        mock_client.get_embedding = AsyncMock(return_value=[0.1] * settings.models.semantic_chunking.embedding_dim)
        mock_session = MagicMock()
        mock_search_chunks.return_value = [
            SimilarChunkRow(chunk_id=1, text="chunk-1 full text", similarity=0.82),
        ]

        with (
            patch("src.storage.repositories.chunk.has_embeddings", return_value=True),
            patch("src.storage.repositories.chunk.get_missing_embedding_chunk_ids", return_value=[]),
            patch("src.storage.repositories.chunk.has_paragraph_embeddings", return_value=True),
            patch("src.storage.repositories.chunk.get_incomplete_paragraph_embedding_chunk_ids", return_value=[]),
            patch("src.storage.vector_schema.validate_chunk_embeddings_schema"),
            patch("src.storage.vector_schema.validate_paragraph_embeddings_schema"),
        ):
            level3 = Level3VectorEvidence(
                session=mock_session,
                run_id="test-run-id",
                embedding_client=mock_client,
            )
            await level3.ensure_level3_ready()
            first = await level3.search_similar_chunks("第一次查询", ensure_ready=False)
            second = await level3.search_similar_chunks("第二次查询", ensure_ready=False)

        assert [row.chunk_id for row in first] == [1]
        assert [row.chunk_id for row in second] == [1]
        assert mock_client.detect_embedding_dimension.await_count == 1
        assert mock_search_chunks.call_count == 2

    @pytest.mark.asyncio
    @patch("src.storage.repositories.chunk.search_similar_paragraphs_within_chunks", return_value=[])
    @patch("src.storage.repositories.chunk.search_similar_chunks")
    async def test_search_similar_chunks_many_batches_embedding_requests(
        self,
        mock_search_chunks: MagicMock,
        mock_search_paragraphs: MagicMock,
    ) -> None:
        """
        创建时间: 2026-04-25
        任务: level3-intent-phase-split
        说明: 多 query 检索应先批量获取 embeddings，再逐条执行 run-scoped chunk search，
              避免 mention/base query 在热路径里重复请求 embedding 服务。
        """
        mock_client = MagicMock()
        mock_client.detect_embedding_dimension = AsyncMock(return_value=settings.models.semantic_chunking.embedding_dim)
        mock_client.embed_texts = AsyncMock(
            return_value=[
                [0.1] * settings.models.semantic_chunking.embedding_dim,
                [0.2] * settings.models.semantic_chunking.embedding_dim,
                [],
            ]
        )
        mock_session = MagicMock()
        mock_search_chunks.side_effect = [
            [SimilarChunkRow(chunk_id=1, text="第一条相似文本", similarity=0.92)],
            [SimilarChunkRow(chunk_id=2, text="第二条相似文本", similarity=0.87)],
        ]

        with (
            patch("src.storage.repositories.chunk.has_embeddings", return_value=True),
            patch("src.storage.repositories.chunk.get_missing_embedding_chunk_ids", return_value=[]),
            patch("src.storage.repositories.chunk.has_paragraph_embeddings", return_value=True),
            patch("src.storage.repositories.chunk.get_incomplete_paragraph_embedding_chunk_ids", return_value=[]),
            patch("src.storage.vector_schema.validate_chunk_embeddings_schema"),
            patch("src.storage.vector_schema.validate_paragraph_embeddings_schema"),
        ):
            level3 = Level3VectorEvidence(
                session=mock_session,
                run_id="test-run-id",
                embedding_client=mock_client,
                top_k=3,
            )
            await level3.ensure_level3_ready()
            results = await level3.search_similar_chunks_many(
                ["第一条查询", "第二条查询", "  "],
                max_chunk_id=9,
                top_k=6,
                ensure_ready=False,
            )

        assert [[row.chunk_id for row in group] for group in results] == [[1], [2], []]
        mock_client.embed_texts.assert_awaited_once_with(["第一条查询", "第二条查询", "  "])
        assert mock_search_chunks.call_count == 2
        assert all(call.kwargs["max_chunk_id"] == 9 for call in mock_search_chunks.call_args_list)
        assert all(call.kwargs["top_k"] == 6 for call in mock_search_chunks.call_args_list)

    @pytest.mark.asyncio
    @patch("src.storage.repositories.chunk.search_similar_paragraphs_within_chunks", return_value=[])
    @patch("src.storage.repositories.chunk.search_similar_chunks")
    async def test_search_similar_chunks_many_falls_back_to_isolated_queries_when_batch_embedding_fails(
        self,
        mock_search_chunks: MagicMock,
        mock_search_paragraphs: MagicMock,
    ) -> None:
        """
        创建时间: 2026-04-25
        任务: fix-batched-level3-failure-isolation
        说明: batched embedding 失败时，应回退到逐 query 执行；单个坏 query 只能丢自己，不能把整批结果清空。
        """
        mock_client = MagicMock()
        mock_client.detect_embedding_dimension = AsyncMock(return_value=settings.models.semantic_chunking.embedding_dim)
        mock_client.embed_texts = AsyncMock(side_effect=RuntimeError("batch request rejected"))

        async def _fake_get_embedding(query_text: str):
            if query_text == "坏查询":
                raise RuntimeError("single query rejected")
            return [0.1] * settings.models.semantic_chunking.embedding_dim

        mock_client.get_embedding = AsyncMock(side_effect=_fake_get_embedding)
        mock_session = MagicMock()
        mock_search_chunks.side_effect = [
            [SimilarChunkRow(chunk_id=1, text="第一条相似文本", similarity=0.92)],
            [SimilarChunkRow(chunk_id=3, text="第三条相似文本", similarity=0.87)],
        ]

        with (
            patch("src.storage.repositories.chunk.has_embeddings", return_value=True),
            patch("src.storage.repositories.chunk.get_missing_embedding_chunk_ids", return_value=[]),
            patch("src.storage.repositories.chunk.has_paragraph_embeddings", return_value=True),
            patch("src.storage.repositories.chunk.get_incomplete_paragraph_embedding_chunk_ids", return_value=[]),
            patch("src.storage.vector_schema.validate_chunk_embeddings_schema"),
            patch("src.storage.vector_schema.validate_paragraph_embeddings_schema"),
        ):
            level3 = Level3VectorEvidence(
                session=mock_session,
                run_id="test-run-id",
                embedding_client=mock_client,
                top_k=3,
            )
            await level3.ensure_level3_ready()
            results = await level3.search_similar_chunks_many(
                ["第一条查询", "坏查询", "第三条查询"],
                max_chunk_id=9,
                top_k=6,
                ensure_ready=False,
            )

        assert [[row.chunk_id for row in group] for group in results] == [[1], [], [3]]
        mock_client.embed_texts.assert_awaited_once_with(["第一条查询", "坏查询", "第三条查询"])
        assert mock_client.get_embedding.await_count == 3
        assert mock_search_chunks.call_count == 2
        assert all(call.kwargs["max_chunk_id"] == 9 for call in mock_search_chunks.call_args_list)
        assert all(call.kwargs["top_k"] == 6 for call in mock_search_chunks.call_args_list)

    @pytest.mark.asyncio
    @patch("src.storage.repositories.chunk.search_similar_paragraphs_within_chunks", return_value=[])
    @patch("src.storage.repositories.chunk.search_similar_chunks")
    async def test_search_similar_chunks_many_isolates_single_query_search_errors_inside_batch(
        self,
        mock_search_chunks: MagicMock,
        mock_search_paragraphs: MagicMock,
    ) -> None:
        """
        创建时间: 2026-04-25
        任务: fix-batched-level3-failure-isolation
        说明: batched embeddings 成功后，某一条 query 的数据库检索异常也只能影响自己。
        """
        mock_client = MagicMock()
        mock_client.detect_embedding_dimension = AsyncMock(return_value=settings.models.semantic_chunking.embedding_dim)
        mock_client.embed_texts = AsyncMock(
            return_value=[
                [0.1] * settings.models.semantic_chunking.embedding_dim,
                [0.2] * settings.models.semantic_chunking.embedding_dim,
                [0.3] * settings.models.semantic_chunking.embedding_dim,
            ]
        )
        mock_session = MagicMock()
        mock_search_chunks.side_effect = [
            [SimilarChunkRow(chunk_id=1, text="第一条相似文本", similarity=0.92)],
            RuntimeError("db timeout"),
            [SimilarChunkRow(chunk_id=3, text="第三条相似文本", similarity=0.87)],
        ]

        with (
            patch("src.storage.repositories.chunk.has_embeddings", return_value=True),
            patch("src.storage.repositories.chunk.get_missing_embedding_chunk_ids", return_value=[]),
            patch("src.storage.repositories.chunk.has_paragraph_embeddings", return_value=True),
            patch("src.storage.repositories.chunk.get_incomplete_paragraph_embedding_chunk_ids", return_value=[]),
            patch("src.storage.vector_schema.validate_chunk_embeddings_schema"),
            patch("src.storage.vector_schema.validate_paragraph_embeddings_schema"),
        ):
            level3 = Level3VectorEvidence(
                session=mock_session,
                run_id="test-run-id",
                embedding_client=mock_client,
                top_k=3,
            )
            await level3.ensure_level3_ready()
            results = await level3.search_similar_chunks_many(
                ["第一条查询", "第二条查询", "第三条查询"],
                max_chunk_id=9,
                top_k=6,
                ensure_ready=False,
            )

        assert [[row.chunk_id for row in group] for group in results] == [[1], [], [3]]
        mock_client.embed_texts.assert_awaited_once_with(["第一条查询", "第二条查询", "第三条查询"])
        assert mock_search_chunks.call_count == 3
        assert all(call.kwargs["max_chunk_id"] == 9 for call in mock_search_chunks.call_args_list)
        assert all(call.kwargs["top_k"] == 6 for call in mock_search_chunks.call_args_list)

    @pytest.mark.asyncio
    @patch("src.storage.repositories.chunk.has_embeddings", return_value=True)
    async def test_search_similar_chunks_empty_query(self, mock_has: MagicMock) -> None:
        """空查询返回空列表"""
        mock_client = MagicMock()
        mock_client.detect_embedding_dimension = AsyncMock(return_value=settings.models.semantic_chunking.embedding_dim)
        mock_session = MagicMock()

        with (
            patch("src.storage.repositories.chunk.has_paragraph_embeddings", return_value=True),
            patch("src.storage.repositories.chunk.get_missing_embedding_chunk_ids", return_value=[]),
            patch("src.storage.repositories.chunk.get_incomplete_paragraph_embedding_chunk_ids", return_value=[]),
            patch("src.storage.vector_schema.validate_chunk_embeddings_schema"),
            patch("src.storage.vector_schema.validate_paragraph_embeddings_schema"),
        ):
            level3 = Level3VectorEvidence(
                session=mock_session,
                run_id="test-run-id",
                embedding_client=mock_client,
            )
            results = await level3.search_similar_chunks("")

        assert results == []

    @pytest.mark.asyncio
    async def test_ensure_level3_ready_fails_on_dimension_mismatch(self) -> None:
        mock_client = MagicMock()
        mock_client.detect_embedding_dimension = AsyncMock(
            return_value=settings.models.semantic_chunking.embedding_dim + 1
        )
        mock_session = MagicMock()
        level3 = Level3VectorEvidence(
            session=mock_session,
            run_id="test-run-id",
            embedding_client=mock_client,
        )

        with pytest.raises(Level3NotReadyError, match="dimension mismatch"):
            await level3.ensure_level3_ready()

    @pytest.mark.asyncio
    @patch("src.storage.repositories.chunk.has_embeddings", return_value=False)
    async def test_ensure_level3_ready_fails_when_embeddings_missing(self, mock_has: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.detect_embedding_dimension = AsyncMock(return_value=settings.models.semantic_chunking.embedding_dim)
        mock_session = MagicMock()
        level3 = Level3VectorEvidence(
            session=mock_session,
            run_id="test-run-id",
            embedding_client=mock_client,
        )

        with (
            patch("src.storage.vector_schema.validate_chunk_embeddings_schema"),
            pytest.raises(Level3NotReadyError, match="embeddings not found"),
        ):
            await level3.ensure_level3_ready()

    @pytest.mark.asyncio
    @patch("src.storage.repositories.chunk.get_missing_embedding_chunk_ids", return_value=[3, 8])
    @patch("src.storage.repositories.chunk.has_embeddings", return_value=True)
    async def test_ensure_level3_ready_fails_when_chunk_embeddings_incomplete(
        self,
        mock_has: MagicMock,
        mock_missing: MagicMock,
    ) -> None:
        """
        创建时间: 2026-04-24
        任务: fix-level3-embedding-partial-write
        说明: chunk embedding 缺失会直接缩小粗召回范围，readiness 必须显式失败。
        """
        mock_client = MagicMock()
        mock_client.detect_embedding_dimension = AsyncMock(return_value=settings.models.semantic_chunking.embedding_dim)
        mock_session = MagicMock()
        level3 = Level3VectorEvidence(
            session=mock_session,
            run_id="test-run-id",
            embedding_client=mock_client,
        )

        with (
            patch("src.storage.vector_schema.validate_chunk_embeddings_schema"),
            pytest.raises(Level3NotReadyError, match="chunk embeddings incomplete"),
        ):
            await level3.ensure_level3_ready()

    @pytest.mark.asyncio
    @patch("src.storage.repositories.chunk.has_paragraph_embeddings", return_value=False)
    @patch("src.storage.repositories.chunk.get_missing_embedding_chunk_ids", return_value=[])
    @patch("src.storage.repositories.chunk.has_embeddings", return_value=True)
    async def test_ensure_level3_ready_fails_when_paragraph_embeddings_missing(
        self,
        mock_has: MagicMock,
        mock_missing: MagicMock,
        mock_has_paragraph: MagicMock,
    ) -> None:
        """
        创建时间: 2026-04-24
        任务: level3-paragraph-readiness
        说明: paragraph embeddings 缺失时 readiness 必须失败，而不是回退到 chunk evidence。
        """
        mock_client = MagicMock()
        mock_client.detect_embedding_dimension = AsyncMock(return_value=settings.models.semantic_chunking.embedding_dim)
        mock_session = MagicMock()
        level3 = Level3VectorEvidence(
            session=mock_session,
            run_id="test-run-id",
            embedding_client=mock_client,
        )

        with (
            patch("src.storage.vector_schema.validate_chunk_embeddings_schema"),
            patch("src.storage.vector_schema.validate_paragraph_embeddings_schema"),
            pytest.raises(Level3NotReadyError, match="paragraph embeddings not found"),
        ):
            await level3.ensure_level3_ready()

    @pytest.mark.asyncio
    @patch("src.storage.repositories.chunk.get_incomplete_paragraph_embedding_chunk_ids", return_value=[2, 4])
    @patch("src.storage.repositories.chunk.get_missing_embedding_chunk_ids", return_value=[])
    @patch("src.storage.repositories.chunk.has_paragraph_embeddings", return_value=True)
    @patch("src.storage.repositories.chunk.has_embeddings", return_value=True)
    async def test_ensure_level3_ready_fails_when_paragraph_embeddings_incomplete(
        self,
        mock_has: MagicMock,
        mock_has_paragraph: MagicMock,
        mock_missing: MagicMock,
        mock_incomplete: MagicMock,
    ) -> None:
        """
        创建时间: 2026-04-24
        任务: level3-paragraph-readiness
        说明: readiness 应报告 paragraph 覆盖不完整的 chunk，避免后续检索时才发现局部证据缺口。
        """
        mock_client = MagicMock()
        mock_client.detect_embedding_dimension = AsyncMock(return_value=settings.models.semantic_chunking.embedding_dim)
        mock_session = MagicMock()
        level3 = Level3VectorEvidence(
            session=mock_session,
            run_id="test-run-id",
            embedding_client=mock_client,
        )

        with (
            patch("src.storage.vector_schema.validate_chunk_embeddings_schema"),
            patch("src.storage.vector_schema.validate_paragraph_embeddings_schema"),
            pytest.raises(Level3NotReadyError, match="paragraph embeddings incomplete"),
        ):
            await level3.ensure_level3_ready()

    @pytest.mark.asyncio
    async def test_ensure_level3_ready_revalidates_after_previous_success(self) -> None:
        """
        创建时间: 2026-04-24
        任务: fix-level3-readiness-revalidation
        说明: provider 每次入口都依赖 async readiness 捕获 schema / paragraph 数据漂移，
              首次成功后不能因为缓存而跳过第二次校验。
        """
        mock_client = MagicMock()
        mock_client.detect_embedding_dimension = AsyncMock(return_value=settings.models.semantic_chunking.embedding_dim)
        mock_session = MagicMock()
        level3 = Level3VectorEvidence(
            session=mock_session,
            run_id="test-run-id",
            embedding_client=mock_client,
        )

        with (
            patch("src.storage.repositories.chunk.has_embeddings", return_value=True),
            patch("src.storage.repositories.chunk.get_missing_embedding_chunk_ids", return_value=[]),
            patch("src.storage.repositories.chunk.has_paragraph_embeddings", side_effect=[True, False]),
            patch("src.storage.repositories.chunk.get_incomplete_paragraph_embedding_chunk_ids", return_value=[]),
            patch("src.storage.vector_schema.validate_chunk_embeddings_schema"),
            patch("src.storage.vector_schema.validate_paragraph_embeddings_schema"),
        ):
            await level3.ensure_level3_ready()
            with pytest.raises(Level3NotReadyError, match="paragraph embeddings not found"):
                await level3.ensure_level3_ready()

        assert mock_client.detect_embedding_dimension.await_count == 2


class TestNarrativeEvidenceServiceLevel3(unittest.TestCase):
    """NarrativeEvidenceService Level 3 集成测试"""

    def test_is_level3_available_false_without_client(self) -> None:
        """没有 EmbeddingClient 时 Level 3 不可用"""
        provider = NarrativeEvidenceService()
        self.assertFalse(provider.is_level3_available())

    @patch("src.storage.repositories.chunk.has_embeddings", return_value=True)
    def test_level3_disabled(self, mock_has: MagicMock) -> None:
        """Level 3 禁用时不可用"""
        mock_client = MagicMock()
        mock_session = MagicMock()

        provider = NarrativeEvidenceService(
            session=mock_session,
            run_id="test-run-id",
            embedding_client=mock_client,
            level3_enabled=False,
        )
        self.assertFalse(provider.is_level3_available())

    @patch("src.storage.repositories.chunk.get_incomplete_paragraph_embedding_chunk_ids", return_value=[])
    @patch("src.storage.repositories.chunk.get_missing_embedding_chunk_ids", return_value=[])
    @patch("src.storage.repositories.chunk.has_paragraph_embeddings", return_value=True)
    @patch("src.storage.repositories.chunk.has_embeddings", return_value=True)
    def test_level3_enabled_and_available(
        self,
        mock_has: MagicMock,
        mock_has_paragraph: MagicMock,
        mock_missing: MagicMock,
        mock_incomplete: MagicMock,
    ) -> None:
        """Level 3 启用且可用"""
        mock_client = MagicMock()
        mock_session = MagicMock()

        provider = NarrativeEvidenceService(
            session=mock_session,
            run_id="test-run-id",
            embedding_client=mock_client,
            level3_enabled=True,
        )
        with (
            patch("src.storage.vector_schema.validate_chunk_embeddings_schema"),
            patch("src.storage.vector_schema.validate_paragraph_embeddings_schema"),
        ):
            self.assertTrue(provider.is_level3_available())

    @patch("src.storage.repositories.chunk.get_incomplete_paragraph_embedding_chunk_ids", return_value=[])
    @patch("src.storage.repositories.chunk.get_missing_embedding_chunk_ids", return_value=[])
    @patch("src.storage.repositories.chunk.has_paragraph_embeddings", return_value=True)
    @patch("src.storage.repositories.chunk.has_embeddings", return_value=True)
    def test_set_embedding_client(
        self,
        mock_has: MagicMock,
        mock_has_paragraph: MagicMock,
        mock_missing: MagicMock,
        mock_incomplete: MagicMock,
    ) -> None:
        """动态设置 EmbeddingClient"""
        provider = NarrativeEvidenceService(level3_enabled=True)
        self.assertFalse(provider.is_level3_available())

        mock_client = MagicMock()
        mock_session = MagicMock()

        provider.set_embedding_client(mock_client)
        provider._level3.set_session(mock_session, "test-run-id")
        with (
            patch("src.storage.vector_schema.validate_chunk_embeddings_schema"),
            patch("src.storage.vector_schema.validate_paragraph_embeddings_schema"),
        ):
            self.assertTrue(provider.is_level3_available())

    def test_level1_can_be_disabled(self) -> None:
        """禁用 Level 1 后 collect_evidence 不应产生 alias_mapping 证据。"""
        graph_repo = MagicMock()
        graph_repo.fetch_alias_map.return_value = {"灰衣人": "白芷"}

        provider = NarrativeEvidenceService(
            graph_repo=graph_repo,
            run_id="test-run-id",
            level1_enabled=False,
        )
        bundle = provider._collect_base_evidence(
            _build_evidence_request(
                requested_names=["灰衣人"],
                current_chunk=3,
                need_level3=False,
            )
        )

        alias_items = [item for item in bundle.structured_evidence if item.evidence_type == "alias_mapping"]
        self.assertEqual(len(alias_items), 0)

    def test_level2_can_be_disabled(self) -> None:
        """禁用 Level 2 后 collect_evidence 不应返回活跃实体候选。"""
        graph_repo = MagicMock()
        graph_repo.fetch_alias_map.return_value = {}
        graph_repo.fetch_active_entities.return_value = [
            {"name": "白芷"},
            {"name": "侯飞白"},
        ]

        provider = NarrativeEvidenceService(
            graph_repo=graph_repo,
            run_id="test-run-id",
            level2_enabled=False,
        )
        bundle = provider._collect_base_evidence(
            _build_evidence_request(
                requested_names=["灰衣人"],
                current_chunk=3,
                need_level3=False,
            )
        )

        self.assertEqual(
            [
                item.metadata.get("name", item.content)
                for item in bundle.local_evidence
                if item.evidence_type == "active_entity"
            ],
            [],
        )

    def test_collect_evidence_keeps_level2_rows_when_level1_hits(self) -> None:
        """结构化证据收集应保留 Level 2 活跃实体，即使 Level 1 已命中。"""
        graph_repo = MagicMock()
        graph_repo.fetch_alias_map.return_value = {"灰衣人": "白芷"}

        provider = NarrativeEvidenceService(
            graph_repo=graph_repo,
            run_id="test-run-id",
            level1_enabled=True,
            level2_enabled=True,
        )
        provider._graph_authority_service = MagicMock()
        provider._graph_authority_service.build_active_entity_view.return_value = [
            ActiveEntityContext(name="白芷"),
            ActiveEntityContext(name="侯飞白"),
        ]

        bundle = provider._collect_base_evidence(
            _build_evidence_request(
                requested_names=["灰衣人"],
                current_chunk=3,
                need_level3=False,
            )
        )

        self.assertEqual(len(bundle.structured_evidence), 1)
        self.assertEqual(bundle.structured_evidence[0].content, "灰衣人 -> 白芷")
        self.assertEqual(
            [
                item.metadata.get("name", item.content)
                for item in bundle.local_evidence
                if item.evidence_type == "active_entity"
            ],
            ["白芷", "侯飞白"],
        )
        self.assertIsNone(render_disambig_candidates(bundle))

    def test_collect_evidence_does_not_swallow_authority_attribute_errors(self) -> None:
        """authority 构建失败时应直接暴露异常，避免静默回退掩盖真实问题。"""
        graph_repo = MagicMock()
        provider = NarrativeEvidenceService(
            graph_repo=graph_repo,
            run_id="test-run-id",
            level1_enabled=False,
            level2_enabled=True,
            level3_enabled=False,
        )
        provider._graph_authority_service = MagicMock()
        provider._graph_authority_service.build_active_entity_view.side_effect = AttributeError("broken authority")

        with pytest.raises(AttributeError, match="broken authority"):
            provider._collect_base_evidence(
                _build_evidence_request(current_chunk=3, need_level3=False)
            )

class TestSharedEvidenceRenderer(unittest.TestCase):
    def test_render_vector_evidence_empty_bundle_returns_none(self) -> None:
        rendered = render_vector_evidence(EvidenceBundle())
        self.assertIsNone(rendered)

    def test_render_vector_evidence_formats_bundle_semantic_rows(self) -> None:
        bundle = EvidenceBundle(
            semantic_evidence=[
                EvidenceItem(
                    evidence_type="semantic_recall",
                    source="chunk_embeddings",
                    content="测试文本1",
                    metadata={"chunk_id": 1, "text": "测试文本1", "similarity": 0.95},
                ),
                EvidenceItem(
                    evidence_type="semantic_recall",
                    source="chunk_embeddings",
                    content="测试文本2",
                    metadata={"chunk_id": 2, "text": "测试文本2", "similarity": 0.85},
                ),
            ]
        )

        rendered = render_vector_evidence(bundle)

        self.assertIsNotNone(rendered)
        assert rendered is not None
        self.assertIn("<Vector_Evidence>", rendered)
        self.assertIn("[Chunk 1]", rendered)
        self.assertIn("[Chunk 2]", rendered)
        self.assertIn("0.95", rendered)
        self.assertIn("0.85", rendered)

    def test_render_vector_evidence_truncates_long_text(self) -> None:
        long_text = "测试" * 200
        bundle = EvidenceBundle(
            semantic_evidence=[
                EvidenceItem(
                    evidence_type="semantic_recall",
                    source="chunk_embeddings",
                    content=long_text,
                    metadata={"chunk_id": 1, "text": long_text, "similarity": 0.95},
                ),
            ]
        )

        rendered = render_vector_evidence(bundle, max_text_len=100)

        self.assertIsNotNone(rendered)
        assert rendered is not None
        self.assertIn("...", rendered)

    def test_render_vector_evidence_prefers_local_preview(self) -> None:
        """
        创建时间: 2026-04-24
        任务: level3-paragraph-rerank
        说明: paragraph rerank 命中时，Vector_Evidence 应优先展示局部 preview，而不是整段 chunk 文本。
        """
        bundle = EvidenceBundle(
            semantic_evidence=[
                EvidenceItem(
                    evidence_type="semantic_recall",
                    source="chunk_embeddings",
                    content="完整 chunk 文本",
                    metadata={
                        "chunk_id": 2,
                        "text": "完整 chunk 文本",
                        "local_preview": "灰衣人站在门外。",
                        "paragraph_index": 1,
                        "similarity": 0.96,
                    },
                ),
            ]
        )

        rendered = render_vector_evidence(bundle)

        self.assertIsNotNone(rendered)
        assert rendered is not None
        self.assertIn("[Chunk 2] [Paragraph 1]", rendered)
        self.assertIn("灰衣人站在门外。", rendered)
        self.assertNotIn("完整 chunk 文本", rendered)

    def test_build_semantic_recall_items_records_paragraph_observation_metadata(self) -> None:
        """
        创建时间: 2026-04-24
        任务: level3-paragraph-readiness
        说明: paragraph rerank 的观察字段应进入 EvidenceItem.metadata，方便后续评测与日志核对。
        """
        from src.rag.evidence_bundle_builder import EvidenceBundleBuilder

        items = EvidenceBundleBuilder().build_semantic_recall_items(
            [
                SimilarChunkRow(
                    chunk_id=2,
                    text="完整 chunk 文本",
                    similarity=0.96,
                    local_preview="灰衣人站在门外。",
                    paragraph_index=1,
                    paragraph_semantic_score=0.96,
                    paragraph_local_start_char=5,
                    paragraph_local_end_char=13,
                    paragraph_global_start_char=205,
                    paragraph_global_end_char=213,
                    chunk_semantic_score=0.81,
                )
            ]
        )

        metadata = items[0].metadata
        assert metadata["evidence_granularity"] == "paragraph"
        assert metadata["rerank_method"] == "chunk_then_paragraph"
        assert metadata["local_preview_len"] == len("灰衣人站在门外。")
        assert metadata["chunk_semantic_score"] == 0.81
        assert metadata["paragraph_semantic_score"] == 0.96
        assert metadata["final_rank_score"] == 0.96
        assert metadata["paragraph_local_start_char"] == 5
        assert metadata["paragraph_global_start_char"] == 205

    def test_render_vector_evidence_ignores_emotion_exemplar_rows(self) -> None:
        bundle = EvidenceBundle(
            semantic_evidence=[
                EvidenceItem(
                    evidence_type="emotion_exemplar",
                    source="chunk_embeddings",
                    content="她笑着收回刀，眸光却冷得发紧。",
                    metadata={
                        "chunk_id": 3,
                        "text": "她笑着收回刀，眸光却冷得发紧。",
                        "similarity": 0.91,
                        "emotional_valence": "mild_negative",
                    },
                )
            ]
        )

        assert render_vector_evidence(bundle) is None

    def test_render_emotion_exemplars_formats_emotion_specific_rows(self) -> None:
        bundle = EvidenceBundle(
            semantic_evidence=[
                EvidenceItem(
                    evidence_type="emotion_exemplar",
                    source="chunk_embeddings",
                    content="她笑着收回刀，眸光却冷得发紧。",
                    metadata={
                        "chunk_id": 3,
                        "text": "她笑着收回刀，眸光却冷得发紧。",
                        "similarity": 0.91,
                        "emotional_valence": "mild_negative",
                    },
                )
            ]
        )

        rendered = render_emotion_exemplars(bundle)

        self.assertIsNotNone(rendered)
        assert rendered is not None
        self.assertIn("<Emotion_Exemplars>", rendered)
        self.assertIn("mild_negative", rendered)
        self.assertIn("[Chunk 3]", rendered)

    def test_provider_and_bundle_no_longer_expose_renderer_methods(self) -> None:
        self.assertFalse(hasattr(EvidenceBundle, "render_disambig_candidates"))
        self.assertFalse(hasattr(EvidenceBundle, "render_vector_evidence"))
        self.assertFalse(hasattr(Level3VectorEvidence, "format_evidence_for_prompt"))

        provider_source = inspect.getsource(NarrativeEvidenceService)
        level3_source = inspect.getsource(Level3VectorEvidence)
        self.assertNotIn("<Disambig_Candidates>", provider_source)
        self.assertNotIn("<Vector_Evidence>", provider_source)
        self.assertNotIn("<Vector_Evidence>", level3_source)


class TestNarrativeEvidenceServiceLevel3Async:
    @pytest.mark.asyncio
    async def test_collect_evidence_with_level3_adds_emotion_exemplar_items(self) -> None:
        """
        修改时间: 2026-04-23
        任务: level3-history-cutoff
        修改说明: provider 层应把 max_chunk_id 原样透传给 Level3 vector 边界。
        """
        provider = NarrativeEvidenceService(level3_enabled=True)
        provider._level3.is_available = MagicMock(return_value=True)
        provider._level3.ensure_level3_ready = AsyncMock(return_value=None)
        provider._level3.search_similar_chunks = AsyncMock(
            return_value=[
                SimilarChunkRow(
                    chunk_id=8,
                    text="她说话时指尖微颤，眼底发冷。",
                    similarity=0.93,
                    emotional_valence="mild_negative",
                ),
                SimilarChunkRow(
                    chunk_id=12,
                    text="他只是点了点头。",
                    similarity=0.81,
                    emotional_valence="neutral",
                ),
            ]
        )

        bundle = await provider.collect(
            _build_evidence_request(
                consumer="annotation_phase1",
                objective="emotion",
                query_text="她抿唇不语，袖口却攥得发白。",
                current_chunk=15,
                max_chunk_id=14,
                exclude_chunk_ids=[15],
                need_level1=False,
                need_level2=False,
                need_level3=True,
                allow_llm_query_expansion=False,
            )
        )

        provider._level3.search_similar_chunks.assert_awaited_once_with(
            "她抿唇不语，袖口却攥得发白。",
            exclude_chunk_ids=[15],
            max_chunk_id=14,
            top_k=20,
            ensure_ready=False,
        )
        semantic_types = [item.evidence_type for item in bundle.semantic_evidence]
        assert semantic_types.count("semantic_recall") == 2
        assert semantic_types.count("emotion_exemplar") == 1
        exemplar = next(item for item in bundle.semantic_evidence if item.evidence_type == "emotion_exemplar")
        assert exemplar.metadata["emotional_valence"] == "mild_negative"
        assert exemplar.metadata["evidence_purpose"] == "emotion"
        assert bundle.request_meta["consumer"] == "annotation_phase1"
        assert bundle.generation_meta["level3_executed"] is True
        assert bundle.generation_meta["query_mode"] == "direct"
        assert bundle.generation_meta["batch_mode"] == "single"
        assert bundle.generation_meta["cache_reuse"] is False

    @pytest.mark.asyncio
    async def test_collect_evidence_with_level3_raises_when_async_readiness_fails_on_required_path(self) -> None:
        """
        创建时间: 2026-04-25
        任务: fix-level3-required-readiness-and-rerank-budget
        说明: required Level3 场景下，若 async readiness 晚于 is_available() 才发现漂移，
              provider 必须继续抛出 Level3NotReadyError，不能静默退回 Level1/2。
        """
        provider = NarrativeEvidenceService(level3_enabled=True)
        provider._level3.is_available = MagicMock(return_value=True)
        provider._level3.ensure_level3_ready = AsyncMock(side_effect=Level3NotReadyError("schema mismatch"))
        provider._level3.search_similar_chunks = AsyncMock()

        with pytest.raises(Level3NotReadyError, match="schema mismatch"):
            await provider.collect(
                _build_evidence_request(
                    objective="identity",
                    query_text="她抿唇不语，袖口却攥得发白。",
                    current_chunk=None,
                    max_chunk_id=14,
                    exclude_chunk_ids=[],
                    need_level3=True,
                    allow_llm_query_expansion=True,
                )
            )

        provider._level3.ensure_level3_ready.assert_awaited_once()
        provider._level3.search_similar_chunks.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_collect_keeps_fallback_bundle_when_query_text_empty(self) -> None:
        """
        创建时间: 2026-04-25
        任务: evidence-service-request-unification
        说明: query_text 为空时只跳过 Level3，不得把 Level1/2 fallback 一起短路掉；
              generation_meta 也应显式记录 empty-query fallback 原因。
        """
        provider = NarrativeEvidenceService(level3_enabled=True)
        provider._level3.ensure_level3_ready = AsyncMock(return_value=None)

        bundle = await provider.collect(
            _build_evidence_request(
                consumer="incremental_disambiguation",
                objective="identity",
                query_text="",
                requested_names=["灰衣人"],
                current_chunk=15,
                max_chunk_id=14,
                need_level3=True,
            )
        )

        assert bundle.request_meta["requested_names"] == ["灰衣人"]
        assert bundle.generation_meta["level3_executed"] is False
        assert bundle.generation_meta["empty_query_fallback_reason"] == "query_text_empty"
        assert bundle.generation_meta["level3_skipped_reason"] == "query_text_empty"
        provider._level3.ensure_level3_ready.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_collect_marks_cache_reuse_on_repeated_request(self) -> None:
        """
        创建时间: 2026-04-25
        任务: evidence-service-request-unification
        说明: 同语义 request 重复进入 service 时，应直接复用 cache，并把 cache_reuse 写进 generation_meta。
        """
        provider = NarrativeEvidenceService(level3_enabled=False)
        request = _build_evidence_request(
            consumer="annotation_phase2",
            objective="foreshadowing",
            query_text="当前 chunk 里埋了前文伏笔。",
            requested_names=["白芷"],
            seed_entities=["白芷"],
            current_chunk=9,
            max_chunk_id=8,
            need_level3=False,
        )

        first_bundle = await provider.collect(request)
        second_bundle = await provider.collect(request)

        assert first_bundle.generation_meta["cache_reuse"] is False
        assert second_bundle.generation_meta["cache_reuse"] is True
        assert second_bundle.request_meta["consumer"] == "annotation_phase2"


if __name__ == "__main__":
    unittest.main()
