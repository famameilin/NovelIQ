"""
Level 3 段落向量检索单元测试

RAG 粒度固定为一个自然段：只测试 run 级段落检索与 readiness，
不再存在 chunk 级召回 / mention / rerank 规格
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.rag.evidence_contracts import EvidenceRequest
from src.rag.evidence_types import EvidenceBundle
from src.rag.retriever import Level3VectorEvidence, NarrativeEvidenceService
from src.storage.repositories.chunk import SimilarParagraphRow


def _paragraph_row(chunk_id: int = 1, text: str = "历史段落证据", similarity: float = 0.9) -> SimilarParagraphRow:
    return SimilarParagraphRow(
        chunk_id=chunk_id,
        paragraph_index=0,
        paragraph_text=text,
        local_start_char=0,
        local_end_char=len(text),
        global_start_char=0,
        global_end_char=len(text),
        similarity=similarity,
    )


def _build_request(
    *,
    query_text: str,
    current_chunk: int | None = None,
    semantic: bool = True,
    requested_names: list[str] | None = None,
) -> EvidenceRequest:
    return EvidenceRequest(
        consumer="annotation_agent",
        objective="identity",
        mode="semantic" if semantic else None,
        query_text=query_text,
        requested_names=requested_names or [],
        seed_entities=[],
        background_entities=[],
        current_chunk=current_chunk,
        need_level1=True,
        need_level2=True,
        top_k=5,
    )


class TestLevel3VectorEvidence:
    def test_is_available_no_embedding_client(self) -> None:
        level3 = Level3VectorEvidence()
        assert level3.is_available() is False

    def test_is_available_no_session(self) -> None:
        level3 = Level3VectorEvidence(embedding_client=MagicMock())
        assert level3.is_available() is False

    def test_is_available_no_run_id(self) -> None:
        level3 = Level3VectorEvidence(session=MagicMock(), embedding_client=MagicMock())
        assert level3.is_available() is False

    @patch("src.storage.repositories.chunk.has_paragraph_embeddings", return_value=False)
    @patch("src.storage.vector_schema.validate_paragraph_embeddings_schema")
    def test_is_available_requires_paragraph_embeddings(
        self,
        mock_validate: MagicMock,
        mock_has_paragraph: MagicMock,
    ) -> None:
        level3 = Level3VectorEvidence(
            session=MagicMock(),
            run_id="run-1",
            embedding_client=MagicMock(),
        )
        assert level3.is_available() is False
        mock_has_paragraph.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_ready_passes_with_paragraph_embeddings(self) -> None:
        mock_client = MagicMock()
        mock_client.detect_embedding_dimension = AsyncMock(return_value=1024)
        with (
            patch("src.storage.repositories.chunk.has_paragraph_embeddings", return_value=True),
            patch("src.storage.repositories.chunk.get_incomplete_paragraph_embedding_chunk_ids", return_value=[]),
            patch("src.storage.vector_schema.validate_paragraph_embeddings_schema"),
        ):
            level3 = Level3VectorEvidence(
                session=MagicMock(),
                run_id="run-1",
                embedding_client=mock_client,
                expected_embedding_dim=1024,
            )
            await level3.ensure_level3_ready()
        assert level3.is_available() is True

    @pytest.mark.asyncio
    async def test_search_similar_paragraphs_returns_paragraph_rows(self) -> None:
        mock_client = MagicMock()
        mock_client.detect_embedding_dimension = AsyncMock(return_value=1024)
        mock_client.get_embedding = AsyncMock(return_value=[0.1] * 1024)
        rows = [_paragraph_row(2), _paragraph_row(5)]
        with (
            patch("src.storage.repositories.chunk.has_paragraph_embeddings", return_value=True),
            patch("src.storage.repositories.chunk.get_incomplete_paragraph_embedding_chunk_ids", return_value=[]),
            patch("src.storage.vector_schema.validate_paragraph_embeddings_schema"),
            patch("src.storage.repositories.chunk.search_similar_paragraphs", return_value=rows) as mock_search,
        ):
            level3 = Level3VectorEvidence(
                session=MagicMock(),
                run_id="run-1",
                embedding_client=mock_client,
                expected_embedding_dim=1024,
            )
            results = await level3.search_similar_paragraphs("谁来过这里", top_k=5)

        assert results == rows
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args.kwargs
        assert call_kwargs["top_k"] == 5
        assert call_kwargs["exclude_chunk_ids"] is None

    @pytest.mark.asyncio
    async def test_search_similar_paragraphs_respects_history_boundary(self) -> None:
        mock_client = MagicMock()
        mock_client.detect_embedding_dimension = AsyncMock(return_value=1024)
        mock_client.get_embedding = AsyncMock(return_value=[0.1] * 1024)
        with (
            patch("src.storage.repositories.chunk.has_paragraph_embeddings", return_value=True),
            patch("src.storage.repositories.chunk.get_incomplete_paragraph_embedding_chunk_ids", return_value=[]),
            patch("src.storage.vector_schema.validate_paragraph_embeddings_schema"),
            patch("src.storage.repositories.chunk.search_similar_paragraphs", return_value=[]) as mock_search,
        ):
            level3 = Level3VectorEvidence(
                session=MagicMock(),
                run_id="run-1",
                embedding_client=mock_client,
                expected_embedding_dim=1024,
            )
            await level3.search_similar_paragraphs("历史", exclude_chunk_ids=[7], max_chunk_id=10, top_k=3)

        call_kwargs = mock_search.call_args.kwargs
        assert call_kwargs["exclude_chunk_ids"] == [7]
        assert call_kwargs["max_chunk_id"] == 10


class TestNarrativeEvidenceServiceLevel3:
    @pytest.mark.asyncio
    async def test_collect_builds_paragraph_evidence(self) -> None:
        mock_client = MagicMock()
        mock_client.detect_embedding_dimension = AsyncMock(return_value=1024)
        mock_client.get_embedding = AsyncMock(return_value=[0.1] * 1024)
        rows = [_paragraph_row(2, "顾霜推开院门"), _paragraph_row(5, "贺重明冷笑一声")]
        with (
            patch("src.storage.repositories.chunk.has_paragraph_embeddings", return_value=True),
            patch("src.storage.repositories.chunk.get_incomplete_paragraph_embedding_chunk_ids", return_value=[]),
            patch("src.storage.vector_schema.validate_paragraph_embeddings_schema"),
            patch("src.storage.repositories.chunk.search_similar_paragraphs", return_value=rows),
            patch(
                "src.storage.repositories.graph.GraphRepository",
                MagicMock(),
            ),
        ):
            service = NarrativeEvidenceService(
                graph_repo=MagicMock(),
                run_id="run-1",
                session=MagicMock(),
                embedding_client=mock_client,
            )
            bundle = await service.collect(
                _build_request(query_text="顾霜是谁", current_chunk=8, requested_names=["顾霜"])
            )

        assert isinstance(bundle, EvidenceBundle)
        assert bundle.generation_meta["semantic_executed"] is True
        semantic_items = [item for item in bundle.historical_evidence if item.evidence_type == "semantic_recall"]
        assert len(semantic_items) == 2
        assert semantic_items[0].content == "顾霜推开院门"
        assert semantic_items[0].metadata["evidence_granularity"] == "paragraph"
        assert semantic_items[0].chunk_id == 2
        assert semantic_items[0].evidence_id == "paragraph:2:0:0:6"
        assert semantic_items[0].metadata["evidence_id"] == "paragraph:2:0:0:6"

    @pytest.mark.asyncio
    async def test_collect_skips_level3_when_not_required(self) -> None:
        service = NarrativeEvidenceService(graph_repo=MagicMock(), run_id="run-1")
        bundle = await service.collect(
            _build_request(query_text="", semantic=False)
        )
        assert bundle.generation_meta["semantic_executed"] is False
        assert bundle.historical_evidence == []
