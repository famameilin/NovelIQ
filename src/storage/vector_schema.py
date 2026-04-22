from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.orm import Session


def _resolve_runtime_schema(session: Session) -> str:
    """
    获取当前会话实际使用的 schema。

    创建时间: 2026-04-22
    创建者: Codex
    任务: fix-test-db-concurrency
    说明: vector schema 不能再把对象写死到 public；
          测试并发时需要跟随当前 search_path 进入各自隔离 schema。
    """
    schema = session.execute(text("SELECT current_schema()")).scalar_one_or_none() or "public"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        raise ValueError(f"invalid schema name: {schema}")
    return schema


def ensure_chunk_embeddings_schema(session: Session, embedding_dim: int) -> None:
    if embedding_dim <= 0:
        raise ValueError(f"embedding dimension must be positive, got {embedding_dim}")

    runtime_schema = _resolve_runtime_schema(session)
    session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    table_regclass = f"{runtime_schema}.chunk_embeddings"
    table_exists = session.execute(text(f"SELECT to_regclass('{table_regclass}')")).scalar_one_or_none()

    if table_exists is None:
        session.execute(
            text(
                f"""
                CREATE TABLE {runtime_schema}.chunk_embeddings (
                    chunk_id INTEGER NOT NULL,
                    run_id VARCHAR(36) NOT NULL,
                    embedding_vector vector({embedding_dim}),
                    created_at VARCHAR(50),
                    PRIMARY KEY (chunk_id, run_id),
                    FOREIGN KEY (chunk_id, run_id)
                        REFERENCES {runtime_schema}.chunks(chunk_id, run_id) ON DELETE CASCADE,
                    FOREIGN KEY (run_id) REFERENCES {runtime_schema}.analysis_runs(run_id) ON DELETE CASCADE
                )
                """
            )
        )
    else:
        vector_type = _get_chunk_embeddings_vector_type(session)
        expected_type = f"vector({embedding_dim})"
        if vector_type != expected_type:
            raise ValueError(
                "chunk_embeddings.embedding_vector type mismatch: "
                f"expected {expected_type}, got {vector_type or 'unknown'}"
            )

    session.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_run_id "
            f"ON {runtime_schema}.chunk_embeddings USING btree (run_id)"
        )
    )
    # Drop the legacy global ANN index so existing environments do not keep
    # using an approximation path that mixes rows from different runs.
    session.execute(text(f"DROP INDEX IF EXISTS {runtime_schema}.idx_chunk_embeddings_vector"))


def validate_chunk_embeddings_schema(session: Session, embedding_dim: int) -> None:
    if embedding_dim <= 0:
        raise ValueError(f"embedding dimension must be positive, got {embedding_dim}")

    runtime_schema = _resolve_runtime_schema(session)
    extension_exists = session.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).scalar_one_or_none()
    if extension_exists is None:
        raise ValueError("pgvector extension 'vector' is not installed")

    table_regclass = f"{runtime_schema}.chunk_embeddings"
    table_exists = session.execute(text(f"SELECT to_regclass('{table_regclass}')")).scalar_one_or_none()
    if table_exists is None:
        raise ValueError("chunk_embeddings table does not exist")

    vector_type = _get_chunk_embeddings_vector_type(session)
    expected_type = f"vector({embedding_dim})"
    if vector_type != expected_type:
        raise ValueError(
            f"chunk_embeddings.embedding_vector type mismatch: expected {expected_type}, got {vector_type or 'unknown'}"
        )


def _get_chunk_embeddings_vector_type(session: Session) -> str | None:
    runtime_schema = _resolve_runtime_schema(session)
    return session.execute(
        text(
            """
            SELECT format_type(a.atttypid, a.atttypmod)
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = :schema_name
              AND c.relname = 'chunk_embeddings'
              AND a.attname = 'embedding_vector'
              AND a.attnum > 0
              AND NOT a.attisdropped
            """
        ),
        {"schema_name": runtime_schema},
    ).scalar_one_or_none()
