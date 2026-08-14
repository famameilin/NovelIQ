import re
from types import SimpleNamespace
from unittest.mock import MagicMock

from pgvector.sqlalchemy import Vector

from src.storage.models import ParagraphEmbedding
from src.storage.repositories.chunk.embedding_ops import (
    ParagraphEmbeddingRow,
    get_incomplete_paragraph_embedding_chunk_ids,
    insert_paragraph_embeddings,
    search_similar_paragraphs,
)


def test_paragraph_embedding_uses_pgvector_column_type() -> None:
    """
    创建时间: 2026-04-24
    任务: level3-paragraph-rerank
    说明: paragraph embedding 表应使用 pgvector 列，保持与 chunk embedding 检索语义一致。
    """
    assert isinstance(ParagraphEmbedding.__table__.c.embedding_vector.type, Vector)


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


def test_search_similar_paragraphs_uses_bare_cosine_distance_for_hnsw() -> None:
    """
    创建时间: 2026-08-13
    任务: P1-1 hnsw-index-miss
    说明: ORDER BY 必须使用裸距离算子 embedding_vector <=> :query（升序），
    阈值下推为 distance <= 1 - threshold，pgvector 才能命中 HNSW ANN 索引；
    包裹成 1 - (embedding_vector <=> :query) 的表达式会让 planner 退化为全表扫描。
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

    results = search_similar_paragraphs(
        session,
        run_id="run-1",
        query_embedding=[0.1] * 1024,
        top_k=5,
        similarity_threshold=0.7,
    )

    statement = session.execute.call_args.args[0]
    compiled_sql = str(statement.compile())
    order_by_pos = compiled_sql.index("ORDER BY")
    # ORDER BY 是裸算子升序：1 - (embedding_vector <=> :q) 包裹表达式不在 ORDER BY 中
    assert (
        "(paragraph_embeddings.embedding_vector <=> :embedding_vector_1) ASC"
        in compiled_sql[order_by_pos:]
    )
    # 阈值下推：WHERE 直接比较裸距离 embedding_vector <=> :q <= :threshold
    assert (
        "(paragraph_embeddings.embedding_vector <=> :embedding_vector_1) <= :param_2"
        in compiled_sql
    )
    # similarity >= 0.7 即 distance <= 0.3（round 消除浮点噪声）
    assert statement.compile().params["param_2"] == 0.3
    assert [row.chunk_id for row in results] == [2]
    assert results[0].paragraph_index == 1
    assert results[0].similarity == 0.93


def test_search_similar_paragraphs_pushes_bounds_and_limit() -> None:
    """2026-08-13 用于验证位置边界、排除集合与 top_k 仍进入 SQL"""
    session = MagicMock()
    session.execute.return_value.all.return_value = []

    search_similar_paragraphs(
        session,
        run_id="run-1",
        query_embedding=[0.1] * 1024,
        top_k=3,
        similarity_threshold=0.5,
        exclude_chunk_ids=[5],
        min_chunk_id=1,
        max_chunk_id=10,
    )

    stmt = session.execute.call_args.args[0]
    compiled_sql = str(stmt.compile())
    assert "LIMIT :param_3" in compiled_sql
    assert "NOT IN" in compiled_sql
    assert re.search(r"chunk_id >= :chunk_id_\d+", compiled_sql) is not None
    assert re.search(r"chunk_id <= :chunk_id_\d+", compiled_sql) is not None


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


def test_get_incomplete_paragraph_embedding_chunk_ids_excludes_empty_text_chunks() -> None:
    """
    创建时间: 2026-08-13
    任务: P2-10 empty-text-chunk
    说明: 空文本 chunk 永远无法产出自然段向量，缺失判定必须排除空串，
    否则空文本 chunk 被永久判为缺失。
    """
    session = MagicMock()
    session.execute.side_effect = [
        MagicMock(all=MagicMock(return_value=[])),
        MagicMock(all=MagicMock(return_value=[])),
        MagicMock(all=MagicMock(return_value=[])),
    ]

    results = get_incomplete_paragraph_embedding_chunk_ids(session, run_id="run-1")

    assert results == []
    missing_statement = session.execute.call_args_list[0].args[0]
    compiled_sql = str(missing_statement.compile(compile_kwargs={"literal_binds": True}))
    assert "length(chunks.text) > 0" in compiled_sql
    # 不再用 is not null 判定：空串会被 length 排除
    assert "text IS NOT NULL" not in compiled_sql
