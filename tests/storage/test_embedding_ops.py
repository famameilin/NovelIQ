import re
from types import SimpleNamespace
from unittest.mock import MagicMock

from pgvector.sqlalchemy import Vector

from src.storage.models import ParagraphEmbedding
from src.storage.repositories.paragraph.embedding_ops import (
    ParagraphEmbeddingRow,
    get_incomplete_paragraph_embedding_paragraph_ids,
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


def test_paragraph_embedding_model_has_paragraph_identity_columns() -> None:
    """
    2026-08-14 二期段落化（§5.2）：旧列（chunk_id/paragraph_index/paragraph_text/
    local/global 坐标）全部移除，段落身份收敛为 paragraphs 表的 paragraph_id。
    """
    columns = set(ParagraphEmbedding.__table__.c.keys())
    assert {"run_id", "paragraph_id", "embedding_vector"} <= columns
    assert {"embedding_model_key", "embedding_dimension", "source_content_hash"} <= columns
    for legacy_column in (
        "chunk_id",
        "paragraph_index",
        "paragraph_text",
        "local_start_char",
        "local_end_char",
        "global_start_char",
        "global_end_char",
    ):
        assert legacy_column not in columns


def test_insert_paragraph_embeddings_writes_paragraph_id_and_metadata() -> None:
    """
    2026-08-14 二期段落化：写入行携带 paragraph_id 与向量，embedding_model_key/
    embedding_dimension 从 settings 取，source_content_hash 对照 paragraphs 表查询。
    """
    session = MagicMock()
    hash_rows = [SimpleNamespace(paragraph_id=7, content_hash="hash-7")]
    session.execute.side_effect = [
        MagicMock(),  # delete 同 run 旧行
        MagicMock(all=MagicMock(return_value=hash_rows)),  # 查 paragraphs content_hash
        MagicMock(),  # insert
    ]

    inserted = insert_paragraph_embeddings(
        session,
        run_id="run-1",
        rows=[
            ParagraphEmbeddingRow(
                paragraph_id=7,
                embedding_vector=[0.3, 0.4],
            )
        ],
    )

    assert inserted == 1
    # 先删后插：第一条 execute 是 delete 同 run 行
    delete_statement = session.execute.call_args_list[0].args[0]
    assert "DELETE FROM paragraph_embeddings" in str(delete_statement.compile())
    _, rows = session.execute.call_args_list[2].args
    assert rows[0]["paragraph_id"] == 7
    assert rows[0]["embedding_vector"] == [0.3, 0.4]
    assert rows[0]["source_content_hash"] == "hash-7"
    assert rows[0]["embedding_dimension"] is not None
    assert rows[0]["created_at"]


def test_insert_paragraph_embeddings_missing_paragraph_hash_is_none() -> None:
    """2026-08-14 用于验证 paragraphs 表缺行时 source_content_hash 不伪造（None）"""
    session = MagicMock()
    session.execute.side_effect = [
        MagicMock(),
        MagicMock(all=MagicMock(return_value=[])),
        MagicMock(),
    ]

    inserted = insert_paragraph_embeddings(
        session,
        run_id="run-1",
        rows=[ParagraphEmbeddingRow(paragraph_id=99, embedding_vector=[0.1])],
    )

    assert inserted == 1
    _, rows = session.execute.call_args_list[2].args
    assert rows[0]["source_content_hash"] is None


def test_insert_paragraph_embeddings_empty_rows_returns_zero() -> None:
    """2026-08-14 用于验证空行列表不写库（仍先删旧行）"""
    session = MagicMock()
    session.execute.side_effect = [MagicMock()]

    inserted = insert_paragraph_embeddings(session, run_id="run-1", rows=[])

    assert inserted == 0
    assert session.execute.call_count == 1


def test_search_similar_paragraphs_uses_bare_cosine_distance_for_hnsw() -> None:
    """
    创建时间: 2026-08-13
    任务: P1-1 hnsw-index-miss
    说明: ORDER BY 必须使用裸距离算子 embedding_vector <=> :query（升序），
    阈值下推为 distance <= 1 - threshold，pgvector 才能命中 HNSW ANN 索引；
    包裹成 1 - (embedding_vector <=> :query) 的表达式会让 planner 退化为全表扫描。

    2026-08-14 二期段落化：SELECT JOIN paragraphs（run_id 对齐）取段落身份与坐标。
    """
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        SimpleNamespace(
            paragraph_id=5,
            chapter_id=2,
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
    # JOIN paragraphs 取段落身份/章节/坐标
    assert "FROM paragraph_embeddings JOIN paragraphs" in compiled_sql
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
    assert [row.paragraph_id for row in results] == [5]
    assert results[0].chapter_id == 2
    assert results[0].chapter_id == 2
    assert results[0].similarity == 0.93


def test_search_similar_paragraphs_pushes_paragraph_bounds_and_limit() -> None:
    """2026-08-14 用于验证段落边界、排除集合与 top_k 仍进入 SQL"""
    session = MagicMock()
    session.execute.return_value.all.return_value = []

    search_similar_paragraphs(
        session,
        run_id="run-1",
        query_embedding=[0.1] * 1024,
        top_k=3,
        similarity_threshold=0.5,
        exclude_paragraph_ids=[5],
        min_paragraph_id=1,
        max_paragraph_id=10,
    )

    stmt = session.execute.call_args.args[0]
    compiled_sql = str(stmt.compile())
    assert "LIMIT :param_3" in compiled_sql
    assert "NOT IN" in compiled_sql
    assert re.search(r"paragraph_id >= :paragraph_id_\d+", compiled_sql) is not None
    assert re.search(r"paragraph_id <= :paragraph_id_\d+", compiled_sql) is not None


def test_get_incomplete_paragraph_embedding_paragraph_ids_combines_missing_and_null_vector() -> None:
    """
    2026-08-14 二期段落化：readiness 缺口以段落为粒度——
    对照 paragraphs 表找出"有段落但无 embedding 行"的段落，叠加空向量段落。
    """
    session = MagicMock()
    session.execute.side_effect = [
        MagicMock(all=MagicMock(return_value=[SimpleNamespace(paragraph_id=2), SimpleNamespace(paragraph_id=5)])),
        MagicMock(all=MagicMock(return_value=[SimpleNamespace(paragraph_id=7)])),
    ]

    results = get_incomplete_paragraph_embedding_paragraph_ids(session, run_id="run-1")

    assert results == [2, 5, 7]
    missing_statement = session.execute.call_args_list[0].args[0]
    null_vector_statement = session.execute.call_args_list[1].args[0]
    # 对照 paragraphs 表 LEFT JOIN 找无 embedding 行的段落
    assert "LEFT OUTER JOIN paragraph_embeddings" in str(missing_statement)
    assert "paragraph_embeddings.run_id IS NULL" in str(missing_statement)
    assert "embedding_vector IS NULL" in str(null_vector_statement)


def test_get_incomplete_paragraph_embedding_paragraph_ids_returns_empty_when_complete() -> None:
    """2026-08-14 用于验证段落全部有向量时缺口为空"""
    session = MagicMock()
    session.execute.side_effect = [
        MagicMock(all=MagicMock(return_value=[])),
        MagicMock(all=MagicMock(return_value=[])),
    ]

    results = get_incomplete_paragraph_embedding_paragraph_ids(session, run_id="run-1")

    assert results == []
