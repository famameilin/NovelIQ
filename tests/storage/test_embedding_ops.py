from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy import text

from src.chunking.chunker import Chunk, split_chunk_paragraphs
from src.preprocess.tokenize import tokenize
from src.storage.repositories.paragraph.embedding_ops import (
    ParagraphEmbeddingRow,
    get_incomplete_paragraph_embedding_paragraph_ids,
    insert_paragraph_embeddings,
    search_similar_paragraphs,
)
from src.storage.repositories.paragraph_repository import ParagraphRepository
from src.storage.vector_schema import ensure_paragraph_embeddings_schema, hnsw_index_uses_halfvec
from tests.support.chapter_annotation_helpers import create_run_with_chunks


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
    assert "(paragraph_embeddings.embedding_vector <=> :embedding_vector_1) ASC" in compiled_sql[order_by_pos:]
    # 阈值下推：WHERE 直接比较裸距离 embedding_vector <=> :q <= :threshold
    assert "(paragraph_embeddings.embedding_vector <=> :embedding_vector_1) <= :param_2" in compiled_sql
    # similarity >= 0.7 即 distance <= 0.3（round 消除浮点噪声）
    assert statement.compile().params["param_2"] == 0.3
    assert [row.paragraph_id for row in results] == [5]
    assert results[0].chapter_id == 2
    assert results[0].chapter_id == 2
    assert results[0].similarity == 0.93


def test_search_similar_paragraphs_compiles_halfvec_cast_beyond_hnsw_dim_limit() -> None:
    """
    2026-09-25 pgvector 对 vector 类型的 HNSW 索引上限 2000 维：>2000 维检索的
    距离表达式必须与建索引同型 cast 成 halfvec，规划器才能命中 halfvec 表达式索引。
    """
    session = MagicMock()
    session.execute.return_value.all.return_value = []

    search_similar_paragraphs(
        session,
        run_id="run-1",
        query_embedding=[0.1] * 2560,
        top_k=5,
        similarity_threshold=0.7,
    )

    compiled_sql = str(session.execute.call_args.args[0].compile())
    assert "AS HALFVEC(2560)" in compiled_sql
    order_by_pos = compiled_sql.index("ORDER BY")
    assert " <=> " in compiled_sql[order_by_pos:]
    # 阈值下推同样走 cast 后的裸距离
    assert "AS HALFVEC(2560)) <=> :param_2) <= :param_3" in compiled_sql


def test_hnsw_index_uses_halfvec_boundary() -> None:
    """2026-09-25 形态判定边界：2000 维（含）以内裸 vector 索引，2001 维起 halfvec"""
    assert hnsw_index_uses_halfvec(1024) is False
    assert hnsw_index_uses_halfvec(2000) is False
    assert hnsw_index_uses_halfvec(2001) is True
    assert hnsw_index_uses_halfvec(2560) is True


def test_search_and_insert_roundtrip_beyond_hnsw_dim_limit(db_session) -> None:
    """
    2026-09-25 运行级验证（Qwen3-Embedding-4B 2560 维 preprocess 实测踩坑）：
    2001 维 ensure 建表（halfvec 表达式索引）+ 写入 + 裸余弦检索全链路可用。
    paragraph_embeddings 不在 conftest 重建清单，测试前后必须 DROP 防维度固化毒化。
    """
    db_session.execute(text("DROP TABLE IF EXISTS paragraph_embeddings CASCADE"))
    db_session.commit()
    ensure_paragraph_embeddings_schema(db_session, 2001)
    db_session.commit()
    try:
        assert hnsw_index_uses_halfvec(2001) is True
        _novel_id, run_id = create_run_with_chunks(
            db_session,
            texts=["灰衣人站在门外。"],
            title="halfvec检索",
        )
        chunks = [Chunk(index=0, text="灰衣人站在门外。", start=0, end=8, chapter_id=1)]
        spans = split_chunk_paragraphs(chunks)
        spans = [replace(span, token_count=len(tokenize(span.text))) for span in spans]
        ParagraphRepository(db_session).insert_paragraphs(run_id, spans)
        db_session.commit()

        insert_paragraph_embeddings(
            db_session,
            run_id,
            [ParagraphEmbeddingRow(paragraph_id=0, embedding_vector=[0.1] * 2001)],
            embedding_dimension=2001,
        )
        db_session.commit()

        results = search_similar_paragraphs(
            db_session,
            run_id=run_id,
            query_embedding=[0.1] * 2001,
            top_k=5,
            similarity_threshold=0.7,
        )
        assert [row.paragraph_id for row in results] == [0]
        assert results[0].similarity > 0.99
    finally:
        db_session.execute(text("DROP TABLE IF EXISTS paragraph_embeddings CASCADE"))
        db_session.commit()


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
