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


def ensure_paragraph_embeddings_schema(session: Session, embedding_dim: int) -> None:
    """2026-08-07 用于创建或验证原文自然段向量表"""
    if embedding_dim <= 0:
        raise ValueError("embedding_dim must be positive")
    session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    schema = _runtime_schema()
    table_regclass = f"{schema}.paragraph_embeddings"
    table_exists = session.execute(
        text("SELECT to_regclass(:table_name)"),
        {"table_name": table_regclass},
    ).scalar_one()
    required_columns = {
        "run_id",
        "chunk_id",
        "paragraph_index",
        "paragraph_text",
        "local_start_char",
        "local_end_char",
        "global_start_char",
        "global_end_char",
        "embedding_vector",
        "created_at",
    }
    existing_columns = _get_table_columns(session, "paragraph_embeddings") if table_exists is not None else set()
    if table_exists is not None and existing_columns != required_columns:
        raise ValueError(
            "paragraph_embeddings schema mismatch: "
            f"expected={sorted(required_columns)} actual={sorted(existing_columns)}"
        )
    if table_exists is None:
        session.execute(
            text(
                f"""
                CREATE TABLE {schema}.paragraph_embeddings (
                    run_id VARCHAR(36) NOT NULL,
                    chunk_id INTEGER NOT NULL,
                    paragraph_index INTEGER NOT NULL,
                    paragraph_text TEXT NOT NULL,
                    local_start_char INTEGER NOT NULL,
                    local_end_char INTEGER NOT NULL,
                    global_start_char INTEGER NOT NULL,
                    global_end_char INTEGER NOT NULL,
                    embedding_vector vector({embedding_dim}),
                    created_at VARCHAR(50),
                    PRIMARY KEY (run_id, chunk_id, paragraph_index),
                    FOREIGN KEY (run_id) REFERENCES {schema}.analysis_runs(run_id) ON DELETE CASCADE,
                    FOREIGN KEY (chunk_id, run_id)
                        REFERENCES {schema}.chunks(chunk_id, run_id) ON DELETE CASCADE
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
    session.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS idx_paragraph_embeddings_run_chunk "
            f"ON {schema}.paragraph_embeddings USING btree (run_id, chunk_id)"
        )
    )


def validate_paragraph_embeddings_schema(session: Session, embedding_dim: int) -> None:
    """2026-08-07 用于校验原文自然段向量表与当前维度合同一致"""
    if embedding_dim <= 0:
        raise ValueError("embedding_dim must be positive")
    schema = _runtime_schema()
    table_exists = session.execute(
        text("SELECT to_regclass(:table_name)"),
        {"table_name": f"{schema}.paragraph_embeddings"},
    ).scalar_one()
    if table_exists is None:
        raise ValueError("paragraph_embeddings table does not exist")
    expected_columns = {
        "run_id",
        "chunk_id",
        "paragraph_index",
        "paragraph_text",
        "local_start_char",
        "local_end_char",
        "global_start_char",
        "global_end_char",
        "embedding_vector",
        "created_at",
    }
    actual_columns = _get_table_columns(session, "paragraph_embeddings")
    if actual_columns != expected_columns:
        raise ValueError(
            "paragraph_embeddings schema mismatch: "
            f"expected={sorted(expected_columns)} actual={sorted(actual_columns)}"
        )
    expected_type = f"vector({embedding_dim})"
    vector_type = _get_embedding_vector_type(session, "paragraph_embeddings")
    if vector_type != expected_type:
        raise ValueError(
            "paragraph_embeddings.embedding_vector type mismatch: "
            f"expected {expected_type}, got {vector_type or 'unknown'}"
        )
