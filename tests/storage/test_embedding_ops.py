"""原文自然段语义向量存取测试（2026-10-16 3NF：向量行在 paragraph_features）

语义向量不再是独立表：向量行是 paragraph_features 的 semantic_vector 行，
模型 key 写在 analysis_runs.embedding_model_key；HNSW 索引是按维度建立的
部分表达式索引，检索 SQL 必须带同维度谓词才能命中索引。
"""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import func, select

from src.config import settings
from src.storage.models import AnalysisRun, ParagraphFeature
from src.storage.repositories.paragraph.embedding_ops import (
    FEATURE_SEMANTIC_VECTOR,
    ParagraphEmbeddingRow,
    get_incomplete_paragraph_embedding_paragraph_ids,
    insert_paragraph_embeddings,
    search_similar_paragraphs,
)
from src.storage.repositories.paragraph_repository import ParagraphRepository
from src.storage.vector_schema import ensure_paragraph_embeddings_schema, hnsw_index_uses_halfvec
from src.text_processing.models import Chunk
from src.text_processing.paragraphs import split_chunk_paragraphs
from src.text_processing.tokenize import tokenize
from tests.support.analysis_factories import insert_test_novel


def _create_run_with_paragraph(db_session, text_of_paragraph: str) -> str:
    """最小 run：novel + 一章正文 + 一个段落（本文件用不到标注）"""
    import uuid

    from src.storage.repositories import ChapterRepository, RunRepository

    novel_id = uuid.uuid4().hex[:8]
    insert_test_novel(novel_id, session=db_session)
    run_id = RunRepository(db_session).create_run(novel_id=novel_id, source_path="test", title="Embedding Test")
    chunks = [Chunk(index=0, text=text_of_paragraph, start=0, end=len(text_of_paragraph), chapter_id=1)]
    ChapterRepository(db_session).insert_chapter_texts(run_id, chunks)
    spans = [replace(span, token_count=len(tokenize(span.text))) for span in split_chunk_paragraphs(chunks)]
    ParagraphRepository(db_session).insert_paragraphs(run_id, spans)
    return run_id


def test_search_similar_paragraphs_uses_bare_cosine_distance_for_hnsw() -> None:
    """
    创建时间: 2026-08-13
    任务: P1-1 hnsw-index-miss
    说明: ORDER BY 必须使用裸距离算子 vector_value <=> :query（升序），
    阈值下推为 distance <= 1 - threshold，pgvector 才能命中 HNSW ANN 索引；
    包裹成 1 - (vector_value <=> :query) 的表达式会让 planner 退化为全表扫描。

    2026-10-16 3NF：向量行来自 paragraph_features，JOIN paragraphs 取身份；
    维度谓词与部分索引同型（vector_dims(vector_value) = N）才能命中。
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
    # 事实源：paragraph_features JOIN paragraphs（章节外连接取 global 坐标投影）
    assert "FROM paragraph_features JOIN paragraphs" in compiled_sql
    assert "LEFT OUTER JOIN chapters" in compiled_sql
    # 与部分索引同谓词：只命中 semantic_vector 且维度等于查询维度
    assert "paragraph_features.feature_code = :feature_code_1" in compiled_sql
    assert "vector_dims(paragraph_features.vector_value) = :vector_dims_1" in compiled_sql
    order_by_pos = compiled_sql.index("ORDER BY")
    # ORDER BY 是裸算子升序：1 - (vector_value <=> :q) 包裹表达式不在 ORDER BY 中
    assert "(paragraph_features.vector_value <=> :vector_value_1) ASC" in compiled_sql[order_by_pos:]
    # 阈值下推：WHERE 直接比较裸距离 vector_value <=> :q <= :threshold
    assert "(paragraph_features.vector_value <=> :vector_value_1) <= :param_2" in compiled_sql
    # similarity >= 0.7 即 distance <= 0.3（round 消除浮点噪声）
    assert statement.compile().params["param_2"] == 0.3
    assert statement.compile().params["vector_dims_1"] == 1024
    assert [row.paragraph_id for row in results] == [5]
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
    assert "(CAST(paragraph_features.vector_value AS HALFVEC(2560)) <=> :param_2) <= :param_3" in compiled_sql


def test_hnsw_index_uses_halfvec_boundary() -> None:
    """2026-09-25 形态判定边界：2000 维（含）以内裸 vector 索引，2001 维起 halfvec"""
    assert hnsw_index_uses_halfvec(1024) is False
    assert hnsw_index_uses_halfvec(2000) is False
    assert hnsw_index_uses_halfvec(2001) is True
    assert hnsw_index_uses_halfvec(2560) is True


def test_insert_paragraph_embeddings_requires_measured_dimension() -> None:
    """2026-10-16 3NF：维度不再逐行保存，缺少实测维度时拒绝写入（不伪造运行模型合同）"""
    session = MagicMock()
    with pytest.raises(ValueError, match="embedding_dimension"):
        insert_paragraph_embeddings(
            session,
            "run-1",
            [ParagraphEmbeddingRow(paragraph_id=0, embedding_vector=[0.1, 0.2])],
        )


def test_search_and_insert_roundtrip_beyond_hnsw_dim_limit(db_session) -> None:
    """
    2026-09-25 运行级验证（Qwen3-Embedding-4B 2560 维 preprocess 实测踩坑）：
    2001 维建 halfvec 部分表达式索引 + 写入 paragraph_features.semantic_vector
    + 裸余弦检索全链路可用；模型 key 写 analysis_runs.embedding_model_key。
    """
    ensure_paragraph_embeddings_schema(db_session, 2001)
    assert hnsw_index_uses_halfvec(2001) is True

    paragraph_text = "灰衣人站在门外。"
    run_id = _create_run_with_paragraph(db_session, paragraph_text)
    db_session.commit()

    inserted = insert_paragraph_embeddings(
        db_session,
        run_id,
        [ParagraphEmbeddingRow(paragraph_id=0, embedding_vector=[0.1] * 2001)],
        embedding_dimension=2001,
    )
    assert inserted == 1
    db_session.commit()

    # 向量行落在 paragraph_features 的 semantic_vector 行（维度由行内向量实际维度表达）
    feature_row = db_session.execute(
        select(
            ParagraphFeature.paragraph_id,
            ParagraphFeature.feature_code,
            func.vector_dims(ParagraphFeature.vector_value).label("dims"),
        ).where(ParagraphFeature.run_id == run_id)
    ).one()
    assert feature_row.feature_code == FEATURE_SEMANTIC_VECTOR
    assert int(feature_row.dims) == 2001
    # 运行模型合同：本次实际使用的嵌入模型 key
    model_key = db_session.execute(
        select(AnalysisRun.embedding_model_key).where(AnalysisRun.run_id == run_id)
    ).scalar_one()
    assert model_key == settings.models.paragraph_embedding.model

    results = search_similar_paragraphs(
        db_session,
        run_id=run_id,
        query_embedding=[0.1] * 2001,
        top_k=5,
        similarity_threshold=0.7,
    )
    assert [row.paragraph_id for row in results] == [0]
    assert results[0].similarity > 0.99
    # 坐标/长度由 chapters.char_offset 与字符长度投影得到
    assert results[0].local_start_char == 0
    assert results[0].local_end_char == len(paragraph_text)
    assert results[0].global_end_char - results[0].global_start_char == len(paragraph_text)


def test_get_incomplete_paragraph_embedding_paragraph_ids_combines_missing_and_null_vector() -> None:
    """
    2026-08-14 二期段落化：readiness 缺口以段落为粒度——
    对照 paragraphs 表找出"有段落但无 semantic_vector 行"的段落，叠加空向量段落。
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
    # 对照 paragraphs 表 LEFT OUTER JOIN semantic_vector 行找缺口段落
    assert "LEFT OUTER JOIN paragraph_features" in str(missing_statement)
    assert "paragraph_features.run_id IS NULL" in str(missing_statement)
    assert "embedding_vector IS NULL" not in str(null_vector_statement)
    assert "paragraph_features.vector_value IS NULL" in str(null_vector_statement)


def test_get_incomplete_paragraph_embedding_paragraph_ids_returns_empty_when_complete() -> None:
    """2026-08-14 用于验证段落全部有向量时缺口为空"""
    session = MagicMock()
    session.execute.side_effect = [
        MagicMock(all=MagicMock(return_value=[])),
        MagicMock(all=MagicMock(return_value=[])),
    ]

    results = get_incomplete_paragraph_embedding_paragraph_ids(session, run_id="run-1")

    assert results == []
