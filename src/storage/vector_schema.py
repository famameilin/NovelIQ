"""
原文自然段语义向量 pgvector schema 管理

语义向量是 paragraph_features 的 semantic_vector 行（通用 vector 列）；
本模块负责建/校验该列上的 HNSW 检索索引：

- 向量列由 ORM/新库初始化建立，本模块不建表、不 DROP 任何对象
- HNSW 索引按维度建立部分表达式索引：固定维度表达式 + 维度谓词，
  查询侧必须带同谓词才能命中
- vector 类型 HNSW 索引上限 2000 维，更高维必须改用 halfvec 表达式索引
  （上限 4000 维），形态判定共用 hnsw_index_uses_halfvec
"""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.storage.db import get_database_schema

#: 语义向量 feature_code（paragraph_features 封闭计算种类）
_FEATURE_SEMANTIC_VECTOR = "semantic_vector"

#: paragraph_features 必须具备的向量列
_REQUIRED_FEATURE_COLUMNS = {
    "run_id",
    "paragraph_id",
    "feature_code",
    "vector_value",
}

# pgvector 对 vector 类型的 HNSW 索引上限 2000 维
_HNSW_MAX_VECTOR_DIM = 2000


def _runtime_schema() -> str:
    """解析当前连接使用的安全 PostgreSQL schema"""
    schema = get_database_schema() or "public"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        raise ValueError(f"invalid runtime schema: {schema}")
    return schema


def _get_table_columns(session: Session, table_name: str) -> set[str]:
    """在当前事务连接中读取运行 schema 的列集合"""
    schema = _runtime_schema()
    return {
        str(column_name)
        for column_name in session.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = :schema_name
                  AND table_name = :table_name
                """
            ),
            {"schema_name": schema, "table_name": table_name},
        ).scalars()
    }


def _get_column_format_type(session: Session, table_name: str, column_name: str) -> str | None:
    """读取指定列的格式化数据库类型"""
    schema = _runtime_schema()
    return session.execute(
        text(
            """
            SELECT format_type(attribute.atttypid, attribute.atttypmod)
            FROM pg_attribute AS attribute
            WHERE attribute.attrelid = to_regclass(:table_name)
              AND attribute.attname = :column_name
              AND NOT attribute.attisdropped
            """
        ),
        {"table_name": f"{schema}.{table_name}", "column_name": column_name},
    ).scalar_one_or_none()


def hnsw_index_uses_halfvec(embedding_dim: int) -> bool:
    """判定段落向量 HNSW 索引是否需要 halfvec 表达式形态"""
    return embedding_dim > _HNSW_MAX_VECTOR_DIM


def _semantic_hnsw_index_name(embedding_dim: int) -> str:
    return f"idx_paragraph_features_semantic_hnsw_{embedding_dim}"


def ensure_paragraph_embeddings_schema(session: Session, embedding_dim: int) -> None:
    """准备原文自然段语义向量的检索索引（按实测维度）

    只校验目标表/列就绪，并按维度建立语义向量的 HNSW 部分表达式索引；
    表结构不兼容（缺列/列类型不是 vector）时抛出 ValueError。
    """
    if embedding_dim <= 0:
        raise ValueError("embedding_dim must be positive")
    session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    schema = _runtime_schema()
    table_regclass = f"{schema}.paragraph_features"
    table_exists = session.execute(
        text("SELECT to_regclass(:table_name)"),
        {"table_name": table_regclass},
    ).scalar_one()
    if table_exists is None:
        raise ValueError(
            "paragraph_features table does not exist: 语义向量依赖新库初始化的段落特征表"
        )
    existing_columns = _get_table_columns(session, "paragraph_features")
    missing = _REQUIRED_FEATURE_COLUMNS - existing_columns
    if missing:
        raise ValueError(
            "paragraph_features schema mismatch (expected "
            f"{sorted(_REQUIRED_FEATURE_COLUMNS)}): missing={sorted(missing)}; "
            "运行时不再自动 DROP/建表，请在新库初始化中建立目标结构"
        )
    vector_type = _get_column_format_type(session, "paragraph_features", "vector_value")
    if vector_type is None or not vector_type.startswith("vector"):
        raise ValueError(
            "paragraph_features.vector_value type mismatch: "
            f"expected vector, got {vector_type or 'unknown'}"
        )

    # 固定维度表达式 + 覆盖该维度的部分索引谓词：
    # 只索引 semantic_vector 行且维度等于本维度，其它维度/POS 向量行不受影响
    index_name = _semantic_hnsw_index_name(embedding_dim)
    predicate = (
        f"feature_code = '{_FEATURE_SEMANTIC_VECTOR}' "
        f"AND vector_dims(vector_value) = {embedding_dim}"
    )
    if hnsw_index_uses_halfvec(embedding_dim):
        index_sql = (
            f"CREATE INDEX IF NOT EXISTS {index_name} "
            f"ON {schema}.paragraph_features USING hnsw "
            f"((vector_value::halfvec({embedding_dim})) halfvec_cosine_ops) "
            f"WHERE {predicate}"
        )
    else:
        index_sql = (
            f"CREATE INDEX IF NOT EXISTS {index_name} "
            f"ON {schema}.paragraph_features USING hnsw "
            f"((vector_value::vector({embedding_dim})) vector_cosine_ops) "
            f"WHERE {predicate}"
        )
    session.execute(text(index_sql))


def _hnsw_index_exists(session: Session, schema: str) -> bool:
    """校验 paragraph_features 是否已建语义向量 HNSW 索引"""
    return (
        session.execute(
            text(
                """
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = :schema_name
                  AND tablename = 'paragraph_features'
                  AND indexdef ILIKE '%USING hnsw%vector_value%'
                LIMIT 1
                """
            ),
            {"schema_name": schema},
        ).scalar_one_or_none()
        is not None
    )


def validate_paragraph_embeddings_schema(session: Session) -> None:
    """校验原文自然段向量存储就绪

    这里只做结构与索引校验，维度校验在 ensure（按探测值）完成。
    """
    schema = _runtime_schema()
    table_exists = session.execute(
        text("SELECT to_regclass(:table_name)"),
        {"table_name": f"{schema}.paragraph_features"},
    ).scalar_one()
    if table_exists is None:
        raise ValueError("paragraph_features table does not exist")
    actual_columns = _get_table_columns(session, "paragraph_features")
    missing = _REQUIRED_FEATURE_COLUMNS - actual_columns
    if missing:
        raise ValueError(
            "paragraph_features schema mismatch: "
            f"expected={sorted(_REQUIRED_FEATURE_COLUMNS)} missing={sorted(missing)}"
        )
    if not _hnsw_index_exists(session, schema):
        # 索引缺失时抛出异常，避免语义检索继续全表扫描
        raise ValueError("paragraph_features missing HNSW index on vector_value (semantic_vector)")
