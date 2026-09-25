from types import SimpleNamespace
from unittest.mock import MagicMock

from src.storage.repositories.paragraph.embedding_ops import (
    get_incomplete_paragraph_embedding_paragraph_ids,
    search_similar_paragraphs,
)


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
