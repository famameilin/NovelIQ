"""paragraph_features 语义向量 HNSW 索引管理测试

语义向量不再是独立表：向量行是 paragraph_features 的 semantic_vector 行。
vector_schema 只负责按实测维度建立/校验该列上的 HNSW 部分表达式索引，
不建表、不 DROP 任何对象；维度上限（2000 维 vector / 4000 维 halfvec）与
查询侧同谓词命中规则共用 hnsw_index_uses_halfvec。
"""

from __future__ import annotations

import pytest
from sqlalchemy import text


def _indexdef(db_session, index_name: str) -> str | None:
    return db_session.execute(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname = current_schema() AND tablename = 'paragraph_features' "
            "AND indexname = :index_name"
        ),
        {"index_name": index_name},
    ).scalar_one_or_none()


def test_ensure_builds_dim_scoped_partial_hnsw_index(db_session) -> None:
    """1024 维：vector(1024) 表达式索引 + 维度谓词（POS 向量与其它维度行不受影响）"""
    from src.storage.vector_schema import _semantic_hnsw_index_name, ensure_paragraph_embeddings_schema

    ensure_paragraph_embeddings_schema(db_session, 1024)
    ensure_paragraph_embeddings_schema(db_session, 1024)  # 幂等：重复调用不报错

    indexdef = _indexdef(db_session, _semantic_hnsw_index_name(1024))
    assert indexdef is not None
    assert "USING hnsw" in indexdef
    assert "vector(1024)" in indexdef
    assert "vector_cosine_ops" in indexdef
    assert "feature_code" in indexdef and "semantic_vector" in indexdef
    assert "vector_dims(vector_value) = 1024" in indexdef


def test_ensure_uses_halfvec_expression_beyond_vector_dim_limit(db_session) -> None:
    """2001 维起 halfvec 表达式索引（pgvector vector 类型 HNSW 上限 2000 维）"""
    from src.storage.vector_schema import _semantic_hnsw_index_name, ensure_paragraph_embeddings_schema

    ensure_paragraph_embeddings_schema(db_session, 2001)

    indexdef = _indexdef(db_session, _semantic_hnsw_index_name(2001))
    assert indexdef is not None
    assert "halfvec(2001)" in indexdef
    assert "halfvec_cosine_ops" in indexdef
    assert "vector_dims(vector_value) = 2001" in indexdef


def test_ensure_rejects_non_positive_dimension(db_session) -> None:
    from src.storage.vector_schema import ensure_paragraph_embeddings_schema

    with pytest.raises(ValueError, match="positive"):
        ensure_paragraph_embeddings_schema(db_session, 0)


def test_ensure_and_validate_do_not_touch_tables(db_session) -> None:
    """运行期结构管理只增索引：不建表、不 DROP，也不修改 columns"""
    from src.storage.vector_schema import ensure_paragraph_embeddings_schema

    columns_before = {
        str(row[0])
        for row in db_session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = 'paragraph_features'"
            )
        ).all()
    }
    ensure_paragraph_embeddings_schema(db_session, 1024)
    columns_after = {
        str(row[0])
        for row in db_session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = 'paragraph_features'"
            )
        ).all()
    }
    assert columns_after == columns_before
    # 本运行 schema 内不得存在旧独立向量表（public 的历史表不在本测试口径）
    legacy_table = db_session.execute(
        text("SELECT to_regclass(:name)"),
        {"name": f"{db_session.execute(text('SELECT current_schema()')).scalar_one()}.paragraph_embeddings"},
    ).scalar_one()
    assert legacy_table is None


def test_validate_requires_hnsw_index(db_session) -> None:
    """缺 HNSW 索引时校验失败（不静默放行全表扫描）"""
    from src.storage.vector_schema import (
        _semantic_hnsw_index_name,
        ensure_paragraph_embeddings_schema,
        validate_paragraph_embeddings_schema,
    )

    ensure_paragraph_embeddings_schema(db_session, 1024)
    validate_paragraph_embeddings_schema(db_session)  # 结构 + 索引齐备

    schema = db_session.execute(text("SELECT current_schema()")).scalar_one()
    existing = [
        str(row[0])
        for row in db_session.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = current_schema() AND tablename = 'paragraph_features' "
                "AND indexdef ILIKE '%USING hnsw%vector_value%'"
            )
        ).all()
    ]
    for index_name in existing:
        db_session.execute(text(f'DROP INDEX IF EXISTS {schema}."{index_name}"'))
    try:
        with pytest.raises(ValueError, match="HNSW"):
            validate_paragraph_embeddings_schema(db_session)
    finally:
        ensure_paragraph_embeddings_schema(db_session, 1024)
    assert _indexdef(db_session, _semantic_hnsw_index_name(1024)) is not None


def test_validate_rejects_wrong_vector_column_type(db_session, monkeypatch) -> None:
    """vector_value 列类型不是 vector 时 ensure 拒绝（不静默写入错误结构）"""
    from src.storage import vector_schema
    from src.storage.vector_schema import ensure_paragraph_embeddings_schema

    real_get_column_format_type = vector_schema._get_column_format_type

    def _fake_format_type(session, table_name, column_name):  # type: ignore[no-untyped-def]
        if table_name == "paragraph_features" and column_name == "vector_value":
            return "double precision"
        return real_get_column_format_type(session, table_name, column_name)

    monkeypatch.setattr(vector_schema, "_get_column_format_type", _fake_format_type)
    with pytest.raises(ValueError, match="type mismatch"):
        ensure_paragraph_embeddings_schema(db_session, 1024)


def test_hnsw_index_uses_halfvec_boundary() -> None:
    """形态判定边界：2000 维（含）以内裸 vector 索引，2001 维起 halfvec"""
    from src.storage.vector_schema import hnsw_index_uses_halfvec

    assert hnsw_index_uses_halfvec(1024) is False
    assert hnsw_index_uses_halfvec(2000) is False
    assert hnsw_index_uses_halfvec(2001) is True
    assert hnsw_index_uses_halfvec(2560) is True
