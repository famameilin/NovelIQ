"""
创建时间: 2026-04-10
创建者: TraeAI
任务: implement-level3-vector-retrieval
说明: Level 3 向量检索单元测试

测试覆盖：
- ChunkEmbedding ORM 模型
- 向量存储与检索功能
- Level3VectorEvidence 可用性检查
- DisambigContextProvider Level 3 集成
- 共享 evidence renderer 边界回归
"""

import inspect
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.local.evidence_renderer_shared import render_disambig_candidates, render_vector_evidence
from src.rag.evidence_types import EvidenceBundle, EvidenceItem
from src.rag.retriever import DisambigContextProvider, Level3NotReadyError, Level3VectorEvidence


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

    @patch("src.storage.repositories.chunk.has_embeddings", return_value=False)
    def test_is_available_no_embeddings_in_db(self, mock_has: MagicMock) -> None:
        """数据库没有 embedding 数据时不可用"""
        mock_client = MagicMock()
        mock_session = MagicMock()

        level3 = Level3VectorEvidence(
            session=mock_session,
            run_id="test-run-id",
            embedding_client=mock_client,
        )
        self.assertFalse(level3.is_available())

    @patch("src.storage.repositories.chunk.has_embeddings", return_value=True)
    def test_is_available_success(self, mock_has: MagicMock) -> None:
        """所有条件满足时可用"""
        mock_client = MagicMock()
        mock_session = MagicMock()

        level3 = Level3VectorEvidence(
            session=mock_session,
            run_id="test-run-id",
            embedding_client=mock_client,
        )
        self.assertTrue(level3.is_available())

class TestLevel3VectorEvidenceAsync:
    """Level3VectorEvidence 异步测试"""

    @pytest.mark.asyncio
    @patch("src.storage.repositories.chunk.search_similar_chunks")
    async def test_search_similar_chunks_success(self, mock_search: MagicMock) -> None:
        """成功检索相似 chunk"""
        mock_client = MagicMock()
        mock_client.detect_embedding_dimension = AsyncMock(return_value=1536)
        mock_client.get_embedding = AsyncMock(return_value=[0.1] * 1536)
        mock_session = MagicMock()

        mock_search.return_value = [
            {"chunk_id": 1, "text": "相似文本", "similarity": 0.9},
        ]

        with (
            patch("src.storage.repositories.chunk.has_embeddings", return_value=True),
            patch("src.storage.vector_schema.validate_chunk_embeddings_schema"),
        ):
            level3 = Level3VectorEvidence(
                session=mock_session,
                run_id="test-run-id",
                embedding_client=mock_client,
            )
            results = await level3.search_similar_chunks("查询文本")

        assert len(results) == 1
        assert results[0]["chunk_id"] == 1

    @pytest.mark.asyncio
    @patch("src.storage.repositories.chunk.has_embeddings", return_value=True)
    async def test_search_similar_chunks_empty_query(self, mock_has: MagicMock) -> None:
        """空查询返回空列表"""
        mock_client = MagicMock()
        mock_client.detect_embedding_dimension = AsyncMock(return_value=1536)
        mock_session = MagicMock()

        with patch("src.storage.vector_schema.validate_chunk_embeddings_schema"):
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
        mock_client.detect_embedding_dimension = AsyncMock(return_value=1024)
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
        mock_client.detect_embedding_dimension = AsyncMock(return_value=1536)
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


class TestDisambigContextProviderLevel3(unittest.TestCase):
    """DisambigContextProvider Level 3 集成测试"""

    def test_is_level3_available_false_without_client(self) -> None:
        """没有 EmbeddingClient 时 Level 3 不可用"""
        provider = DisambigContextProvider()
        self.assertFalse(provider.is_level3_available())

    @patch("src.storage.repositories.chunk.has_embeddings", return_value=True)
    def test_level3_disabled(self, mock_has: MagicMock) -> None:
        """Level 3 禁用时不可用"""
        mock_client = MagicMock()
        mock_session = MagicMock()

        provider = DisambigContextProvider(
            session=mock_session,
            run_id="test-run-id",
            embedding_client=mock_client,
            level3_enabled=False,
        )
        self.assertFalse(provider.is_level3_available())

    @patch("src.storage.repositories.chunk.has_embeddings", return_value=True)
    def test_level3_enabled_and_available(self, mock_has: MagicMock) -> None:
        """Level 3 启用且可用"""
        mock_client = MagicMock()
        mock_session = MagicMock()

        provider = DisambigContextProvider(
            session=mock_session,
            run_id="test-run-id",
            embedding_client=mock_client,
            level3_enabled=True,
        )
        self.assertTrue(provider.is_level3_available())

    @patch("src.storage.repositories.chunk.has_embeddings", return_value=True)
    def test_set_embedding_client(self, mock_has: MagicMock) -> None:
        """动态设置 EmbeddingClient"""
        provider = DisambigContextProvider(level3_enabled=True)
        self.assertFalse(provider.is_level3_available())

        mock_client = MagicMock()
        mock_session = MagicMock()

        provider.set_embedding_client(mock_client)
        provider._level3.set_session(mock_session, "test-run-id")
        self.assertTrue(provider.is_level3_available())

    def test_level1_can_be_disabled(self) -> None:
        """禁用 Level 1 后 collect_evidence 不应产生 alias_mapping 证据。"""
        graph_repo = MagicMock()
        graph_repo.fetch_alias_map.return_value = {"灰衣人": "白芷"}

        provider = DisambigContextProvider(
            graph_repo=graph_repo,
            run_id="test-run-id",
            level1_enabled=False,
        )
        bundle = provider.collect_evidence(names_in_chunk=["灰衣人"], current_chunk=3)

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

        provider = DisambigContextProvider(
            graph_repo=graph_repo,
            run_id="test-run-id",
            level2_enabled=False,
        )
        bundle = provider.collect_evidence(names_in_chunk=["灰衣人"], current_chunk=3)

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
        graph_repo.fetch_active_entities.return_value = [
            {"name": "白芷"},
            {"name": "侯飞白"},
        ]

        provider = DisambigContextProvider(
            graph_repo=graph_repo,
            run_id="test-run-id",
            level1_enabled=True,
            level2_enabled=True,
        )

        bundle = provider.collect_evidence(["灰衣人"], current_chunk=3)

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

    def test_provider_and_bundle_no_longer_expose_renderer_methods(self) -> None:
        self.assertFalse(hasattr(EvidenceBundle, "render_disambig_candidates"))
        self.assertFalse(hasattr(EvidenceBundle, "render_vector_evidence"))
        self.assertFalse(hasattr(Level3VectorEvidence, "format_evidence_for_prompt"))

        provider_source = inspect.getsource(DisambigContextProvider)
        level3_source = inspect.getsource(Level3VectorEvidence)
        self.assertNotIn("<Disambig_Candidates>", provider_source)
        self.assertNotIn("<Vector_Evidence>", provider_source)
        self.assertNotIn("<Vector_Evidence>", level3_source)


if __name__ == "__main__":
    unittest.main()
