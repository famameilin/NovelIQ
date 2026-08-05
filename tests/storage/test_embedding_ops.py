from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pgvector.sqlalchemy import Vector

from src.storage.models import ChunkEmbedding, ParagraphEmbedding
from src.storage.repositories.chunk.embedding_ops import (
    ParagraphEmbeddingRow,
    get_chunk_embedding,
    get_incomplete_paragraph_embedding_chunk_ids,
    insert_chunk_embeddings,
    insert_paragraph_embeddings,
    search_similar_chunks,
    search_similar_paragraphs_within_chunks,
)


def test_chunk_embedding_uses_pgvector_column_type() -> None:
    assert isinstance(ChunkEmbedding.__table__.c.embedding_vector.type, Vector)


def test_paragraph_embedding_uses_pgvector_column_type() -> None:
    """
    创建时间: 2026-04-24
    任务: level3-paragraph-rerank
    说明: paragraph embedding 表应使用 pgvector 列，保持与 chunk embedding 检索语义一致。
    """
    assert isinstance(ParagraphEmbedding.__table__.c.embedding_vector.type, Vector)


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


def test_insert_paragraph_embeddings_preserves_local_metadata() -> None:
    """
    创建时间: 2026-04-24
    任务: level3-paragraph-rerank
    说明: paragraph embedding 写入时必须保留 chunk 内段落序号与局部字符范围。
    """
    session = MagicMock()

    inserted = insert_paragraph_embeddings(
        session,
        run_id="run-1",
        rows=[
            ParagraphEmbeddingRow(
                chunk_id=2,
                paragraph_index=1,
                paragraph_text="灰衣人站在门外。",
                local_start_char=5,
                local_end_char=13,
                global_start_char=105,
                global_end_char=113,
                embedding_vector=[0.3, 0.4],
            )
        ],
    )

    assert inserted == 1
    _, rows = session.execute.call_args_list[1].args
    assert rows[0]["paragraph_index"] == 1
    assert rows[0]["local_start_char"] == 5
    assert rows[0]["local_end_char"] == 13
    assert rows[0]["global_start_char"] == 105
    assert rows[0]["global_end_char"] == 113
    assert rows[0]["embedding_vector"] == [0.3, 0.4]


def test_get_chunk_embedding_returns_python_list() -> None:
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = (0.1, 0.2, 0.3)

    result = get_chunk_embedding(session, run_id="run-1", chunk_id=1)

    assert result == [0.1, 0.2, 0.3]


def test_search_similar_chunks_pushes_exclusions_into_sql() -> None:
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        SimpleNamespace(chunk_id=2, text="chunk-2", emotional_valence="mild_negative", similarity=0.91),
        SimpleNamespace(chunk_id=3, text="chunk-3", emotional_valence=None, similarity=0.88),
    ]

    with patch(
        "src.storage.repositories.annotation.AnnotationRepository.fetch_chunk_annotations_full",
        return_value=[
            SimpleNamespace(chunk_id=2, emotional_valence="mild_negative"),
            SimpleNamespace(chunk_id=3, emotional_valence="neutral"),
        ],
    ):
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
    assert [row.chunk_id for row in results] == [2, 3]
    assert results[0].emotional_valence == "mild_negative"


def test_search_similar_chunks_pushes_history_cutoff_into_sql() -> None:
    """
    创建时间: 2026-04-23
    任务: level3-history-cutoff
    说明: Level3 检索必须在 SQL 层应用 max_chunk_id，防止增量路径召回未来 chunk。
    """
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        SimpleNamespace(chunk_id=3, text="chunk-3", emotional_valence=None, similarity=0.88),
    ]

    with patch(
        "src.storage.repositories.annotation.AnnotationRepository.fetch_chunk_annotations_full",
        return_value=[],
    ):
        results = search_similar_chunks(
            session,
            run_id="run-1",
            query_embedding=[0.1, 0.2],
            max_chunk_id=3,
        )

    statement = session.execute.call_args.args[0]
    assert "chunk_id <= :chunk_id_1" in str(statement)
    assert [row.chunk_id for row in results] == [3]


def test_search_similar_chunks_without_exclusions_keeps_sql_simple() -> None:
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        SimpleNamespace(chunk_id=1, text="chunk-1", emotional_valence="neutral", similarity=0.95),
    ]

    with patch(
        "src.storage.repositories.annotation.AnnotationRepository.fetch_chunk_annotations_full",
        return_value=[SimpleNamespace(chunk_id=1, emotional_valence="neutral")],
    ):
        results = search_similar_chunks(
            session,
            run_id="run-1",
            query_embedding=[0.1, 0.2],
        )

    statement = session.execute.call_args.args[0]
    assert "NOT IN" not in str(statement)
    assert len(results) == 1
    assert results[0].chunk_id == 1
    assert results[0].text == "chunk-1"
    assert results[0].emotional_valence == "neutral"
    assert results[0].similarity == 0.95


def test_search_similar_paragraphs_requires_candidate_chunk_ids() -> None:
    """
    创建时间: 2026-04-24
    任务: level3-paragraph-rerank
    说明: paragraph 检索必须由 chunk 粗召回限定范围，空候选不应触发全库搜索。
    """
    session = MagicMock()

    results = search_similar_paragraphs_within_chunks(
        session,
        run_id="run-1",
        query_embedding=[0.1, 0.2],
        chunk_ids=[],
    )

    assert results == []
    session.execute.assert_not_called()


def test_search_similar_paragraphs_limits_sql_to_candidate_chunks() -> None:
    """
    创建时间: 2026-04-24
    任务: level3-paragraph-rerank
    说明: paragraph rerank 只能在候选 chunk_ids 内执行，不能退化成全库 paragraph 召回。
    """
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        SimpleNamespace(
            chunk_id=2,
            paragraph_index=1,
            paragraph_text="灰衣人站在门外。",
            local_start_char=5,
            local_end_char=13,
            global_start_char=105,
            global_end_char=113,
            similarity=0.93,
        )
    ]

    results = search_similar_paragraphs_within_chunks(
        session,
        run_id="run-1",
        query_embedding=[0.1, 0.2],
        chunk_ids=[2, 2, 3],
    )

    statement = session.execute.call_args.args[0]
    assert "chunk_id IN" in str(statement)
    assert "row_number()" in str(statement)
    assert "PARTITION BY paragraph_embeddings.chunk_id" in str(statement)
    assert "paragraph_rank" in str(statement)
    assert [row.chunk_id for row in results] == [2]
    assert results[0].paragraph_index == 1
    assert results[0].paragraph_text == "灰衣人站在门外。"
    assert results[0].local_start_char == 5
    assert results[0].global_start_char == 105


def test_get_incomplete_paragraph_embedding_chunk_ids_combines_missing_gapped_and_null_vector_rows() -> None:
    """
    创建时间: 2026-04-24
    任务: level3-paragraph-readiness
    说明: readiness 缺失检测需要同时报告完全缺 paragraph row、paragraph_index 不连续以及空向量的 chunk。
    """
    session = MagicMock()
    session.execute.side_effect = [
        MagicMock(all=MagicMock(return_value=[SimpleNamespace(chunk_id=2)])),
        MagicMock(all=MagicMock(return_value=[SimpleNamespace(chunk_id=5)])),
        MagicMock(all=MagicMock(return_value=[SimpleNamespace(chunk_id=7)])),
    ]

    results = get_incomplete_paragraph_embedding_chunk_ids(session, run_id="run-1")

    assert results == [2, 5, 7]
    missing_statement = session.execute.call_args_list[0].args[0]
    gapped_statement = session.execute.call_args_list[1].args[0]
    null_vector_statement = session.execute.call_args_list[2].args[0]
    assert "NOT (EXISTS" in str(missing_statement)
    assert "HAVING" in str(gapped_statement)
    assert "embedding_vector IS NULL" in str(null_vector_statement)
