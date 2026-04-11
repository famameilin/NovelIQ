from unittest.mock import MagicMock

from pgvector.sqlalchemy import Vector

from src.storage.models import ChunkEmbedding
from src.storage.repositories.chunk.embedding_ops import get_chunk_embedding
from src.storage.repositories.chunk.embedding_ops import insert_chunk_embeddings
from src.storage.repositories.chunk.embedding_ops import search_similar_chunks


def test_chunk_embedding_uses_pgvector_column_type() -> None:
    assert isinstance(ChunkEmbedding.__table__.c.embedding_vector.type, Vector)


def test_insert_chunk_embeddings_preserves_vector_payloads() -> None:
    session = MagicMock()

    inserted = insert_chunk_embeddings(
        session,
        run_id="run-1",
        embeddings=[(1, [0.1, 0.2])],
    )

    assert inserted == 1
    _, rows = session.execute.call_args_list[1].args
    assert rows[0]["embedding_vector"] == [0.1, 0.2]


def test_get_chunk_embedding_returns_python_list() -> None:
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = (0.1, 0.2, 0.3)

    result = get_chunk_embedding(session, run_id="run-1", chunk_id=1)

    assert result == [0.1, 0.2, 0.3]


def test_search_similar_chunks_pushes_exclusions_into_sql() -> None:
    session = MagicMock()
    session.execute.return_value.fetchall.return_value = [
        (2, "chunk-2", 0.91),
        (3, "chunk-3", 0.88),
    ]

    results = search_similar_chunks(
        session,
        run_id="run-1",
        query_embedding=[0.1, 0.2],
        top_k=2,
        similarity_threshold=0.7,
        exclude_chunk_ids=[1, 4],
    )

    statement = session.execute.call_args.args[0]
    assert "NOT IN" in str(statement)
    assert [row["chunk_id"] for row in results] == [2, 3]


def test_search_similar_chunks_without_exclusions_keeps_sql_simple() -> None:
    session = MagicMock()
    session.execute.return_value.fetchall.return_value = [
        (1, "chunk-1", 0.95),
    ]

    results = search_similar_chunks(
        session,
        run_id="run-1",
        query_embedding=[0.1, 0.2],
    )

    statement = session.execute.call_args.args[0]
    assert "NOT IN" not in str(statement)
    assert results == [{"chunk_id": 1, "text": "chunk-1", "similarity": 0.95}]
