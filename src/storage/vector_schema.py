"""
原文自然段 pgvector schema 管理
"""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.storage.db import get_database_schema


def _runtime_schema() -> str:
    """2026-08-07 用于解析当前连接使用的安全 PostgreSQL schema"""
    schema = get_database_schema() or "public"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        raise ValueError(f"invalid runtime schema: {schema}")
    return schema


def _get_table_columns(session: Session, table_name: str) -> set[str]:
    """2026-08-07 用于在当前事务连接中读取运行 schema 的列集合"""
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


def _get_embedding_vector_type(session: Session, table_name: str) -> str | None:
    """2026-08-07 用于读取 pgvector 列的格式化数据库类型"""
    schema = _runtime_schema()
    return session.execute(
        text(
            """
            SELECT format_type(attribute.atttypid, attribute.atttypmod)
            FROM pg_attribute AS attribute
            WHERE attribute.attrelid = to_regclass(:table_name)
              AND attribute.attname = 'embedding_vector'
              AND NOT attribute.attisdropped
            """
        ),
        {"table_name": f"{schema}.{table_name}"},
    ).scalar_one_or_none()


# 二期段落化（§5.2）新结构：旧列（chunk_id/paragraph_index/paragraph_text/
# local_*/global_*）全部移除，段落身份收敛为 paragraphs 表的 paragraph_id。
# 旧数据旧代码不兼容：列集合不匹配时直接 DROP TABLE 后重建，数据不回填。
_REQUIRED_PARAGRAPH_EMBEDDING_COLUMNS = {
    "run_id",
    "paragraph_id",
    "embedding_vector",
    "embedding_model_key",
    "embedding_dimension",
    "source_content_hash",
    "created_at",
}


def ensure_paragraph_embeddings_schema(session: Session, embedding_dim: int) -> None:
    """2026-08-07 用于创建或验证原文自然段向量表

    2026-08-14 二期段落化：列集合与当前结构不一致（含旧结构）时，
    DROP TABLE 后按新结构重建；重建不迁移旧数据（不兼容旧数据策略）。
    """
    if embedding_dim <= 0:
        raise ValueError("embedding_dim must be positive")
    session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    schema = _runtime_schema()
    table_regclass = f"{schema}.paragraph_embeddings"
    table_exists = session.execute(
        text("SELECT to_regclass(:table_name)"),
        {"table_name": table_regclass},
    ).scalar_one()
    existing_columns = _get_table_columns(session, "paragraph_embeddings") if table_exists is not None else set()
    if table_exists is not None and existing_columns != _REQUIRED_PARAGRAPH_EMBEDDING_COLUMNS:
        # 2026-08-14 二期段落化：旧结构（含一期段落 embedding 结构）直接 DROP 重建，
        # 不尝试 ALTER 兼容——旧列与新结构语义完全不同，且旧数据不回填
        session.execute(text(f"DROP TABLE {table_regclass}"))
        table_exists = None
    if table_exists is None:
        session.execute(
            text(
                f"""
                CREATE TABLE {schema}.paragraph_embeddings (
                    run_id VARCHAR(36) NOT NULL,
                    paragraph_id INTEGER NOT NULL,
                    embedding_vector vector({embedding_dim}),
                    embedding_model_key VARCHAR,
                    embedding_dimension INTEGER,
                    source_content_hash VARCHAR(64),
                    created_at VARCHAR(50),
                    PRIMARY KEY (run_id, paragraph_id),
                    FOREIGN KEY (run_id) REFERENCES {schema}.analysis_runs(run_id) ON DELETE CASCADE,
                    FOREIGN KEY (run_id, paragraph_id)
                        REFERENCES {schema}.paragraphs(run_id, paragraph_id) ON DELETE CASCADE
                )
                """
            )
        )
    vector_type = _get_embedding_vector_type(session, "paragraph_embeddings")
    expected_type = f"vector({embedding_dim})"
    if vector_type != expected_type:
        raise ValueError(
            "paragraph_embeddings.embedding_vector type mismatch: "
            f"expected {expected_type}, got {vector_type or 'unknown'}"
        )
    session.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS idx_paragraph_embeddings_run_id "
            f"ON {schema}.paragraph_embeddings USING btree (run_id)"
        )
    )
    # 2026-08-13 P2：章节 Agent 语义检索（search_similar_paragraphs）此前对同 run 全量
    # 向量做余弦全表扫描，加 HNSW ANN 索引（需 pgvector ≥ 0.5）；查询按向量距离检索后
    # 再叠加 run_id 边界过滤即可命中
    session.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS idx_paragraph_embeddings_embedding_hnsw "
            f"ON {schema}.paragraph_embeddings USING hnsw (embedding_vector vector_cosine_ops)"
        )
    )


def _hnsw_index_exists(session: Session, schema: str) -> bool:
    """2026-08-13 用于校验 paragraph_embeddings 是否已建 HNSW 向量索引"""
    return (
        session.execute(
            text(
                """
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = :schema_name
                  AND tablename = 'paragraph_embeddings'
                  AND indexdef ILIKE '%USING hnsw%embedding_vector%'
                LIMIT 1
                """
            ),
            {"schema_name": schema},
        ).scalar_one_or_none()
        is not None
    )


def validate_paragraph_embeddings_schema(session: Session, embedding_dim: int) -> None:
    """2026-08-07 用于校验原文自然段向量表与当前维度合同一致（二期段落化列集）"""
    if embedding_dim <= 0:
        raise ValueError("embedding_dim must be positive")
    schema = _runtime_schema()
    table_exists = session.execute(
        text("SELECT to_regclass(:table_name)"),
        {"table_name": f"{schema}.paragraph_embeddings"},
    ).scalar_one()
    if table_exists is None:
        raise ValueError("paragraph_embeddings table does not exist")
    actual_columns = _get_table_columns(session, "paragraph_embeddings")
    if actual_columns != _REQUIRED_PARAGRAPH_EMBEDDING_COLUMNS:
        raise ValueError(
            "paragraph_embeddings schema mismatch: "
            f"expected={sorted(_REQUIRED_PARAGRAPH_EMBEDDING_COLUMNS)} "
            f"actual={sorted(actual_columns)}"
        )
    expected_type = f"vector({embedding_dim})"
    vector_type = _get_embedding_vector_type(session, "paragraph_embeddings")
    if vector_type != expected_type:
        raise ValueError(
            "paragraph_embeddings.embedding_vector type mismatch: "
            f"expected {expected_type}, got {vector_type or 'unknown'}"
        )
    if not _hnsw_index_exists(session, schema):
        # 2026-08-13 P2：索引缺失时不再静默通过，避免语义检索继续全表扫描
        raise ValueError("paragraph_embeddings missing HNSW index on embedding_vector")
