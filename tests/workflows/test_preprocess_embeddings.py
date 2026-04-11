from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.chunking.chunker import Chunk
from src.workflows.preprocess import _generate_chunk_embeddings


@pytest.mark.asyncio
async def test_generate_chunk_embeddings_uses_chunk_index_as_chunk_id() -> None:
    chunks = [
        Chunk(index=7, text="第一段文本", start=0, end=4),
        Chunk(index=8, text="第二段文本", start=5, end=9),
    ]
    mock_client = MagicMock()
    mock_client.detect_embedding_dimension = AsyncMock(return_value=1536)
    mock_client.get_embedding = AsyncMock(side_effect=[[0.1, 0.2], [0.3, 0.4]])

    with (
        patch("src.models.local.embedding.EmbeddingClient", return_value=mock_client),
        patch("src.workflows.preprocess.ensure_chunk_embeddings_schema") as mock_ensure_schema,
        patch("src.storage.repositories.chunk.insert_chunk_embeddings") as mock_insert_embeddings,
    ):
        inserted = await _generate_chunk_embeddings(
            session=MagicMock(),
            run_id="run-1",
            all_chunks=chunks,
        )

    assert inserted == 2
    mock_client.detect_embedding_dimension.assert_awaited_once()
    mock_ensure_schema.assert_called_once()
    assert mock_client.get_embedding.await_args_list[0].kwargs["chunk_id"] == 7
    assert mock_client.get_embedding.await_args_list[1].kwargs["chunk_id"] == 8
    assert mock_insert_embeddings.call_args.args[2] == [
        (7, [0.1, 0.2]),
        (8, [0.3, 0.4]),
    ]


@pytest.mark.asyncio
async def test_generate_chunk_embeddings_fails_fast_on_dimension_mismatch() -> None:
    mock_client = MagicMock()
    mock_client.detect_embedding_dimension = AsyncMock(return_value=1024)
    mock_client.get_embedding = AsyncMock()

    with (
        patch("src.models.local.embedding.EmbeddingClient", return_value=mock_client),
        patch("src.workflows.preprocess.ensure_chunk_embeddings_schema") as mock_ensure_schema,
    ):
        with pytest.raises(ValueError, match="dimension mismatch"):
            await _generate_chunk_embeddings(
                session=MagicMock(),
                run_id="run-1",
                all_chunks=[Chunk(index=1, text="测试文本", start=0, end=4)],
            )

    mock_client.get_embedding.assert_not_called()
    mock_ensure_schema.assert_not_called()
