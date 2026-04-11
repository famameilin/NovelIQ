from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def ensure_chunk_embeddings_schema(session: Session, embedding_dim: int) -> None:
    if embedding_dim <= 0:
        raise ValueError(f"embedding dimension must be positive, got {embedding_dim}")

    session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    table_exists = session.execute(
        text("SELECT to_regclass('public.chunk_embeddings')")
    ).scalar_one_or_none()

    if table_exists is None:
        session.execute(
            text(
                f"""
                CREATE TABLE public.chunk_embeddings (
                    chunk_id INTEGER NOT NULL,
                    run_id VARCHAR(36) NOT NULL,
                    embedding_vector vector({embedding_dim}),
                    created_at VARCHAR(50),
                    PRIMARY KEY (chunk_id, run_id),
                    FOREIGN KEY (chunk_id, run_id) REFERENCES public.chunks(chunk_id, run_id) ON DELETE CASCADE,
                    FOREIGN KEY (run_id) REFERENCES public.analysis_runs(run_id) ON DELETE CASCADE
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
            "CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_run_id "
            "ON public.chunk_embeddings USING btree (run_id)"
        )
    )
    session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_vector "
            "ON public.chunk_embeddings USING hnsw (embedding_vector vector_cosine_ops)"
        )
    )


def _get_chunk_embeddings_vector_type(session: Session) -> str | None:
    return session.execute(
        text(
            """
            SELECT format_type(a.atttypid, a.atttypmod)
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relname = 'chunk_embeddings'
              AND a.attname = 'embedding_vector'
              AND a.attnum > 0
              AND NOT a.attisdropped
            """
        )
    ).scalar_one_or_none()
