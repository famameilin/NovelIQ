from unittest.mock import MagicMock

from src.storage.repositories.chunk.embedding_ops import search_similar_chunks


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

    statement, params = session.execute.call_args.args
    assert "NOT IN" in str(statement)
    assert params["exclude_chunk_ids"] == [1, 4]
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

    statement, params = session.execute.call_args.args
    assert "NOT IN" not in str(statement)
    assert "exclude_chunk_ids" not in params
    assert results == [{"chunk_id": 1, "text": "chunk-1", "similarity": 0.95}]

