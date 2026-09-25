from __future__ import annotations

from sqlalchemy import text


def test_validate_paragraph_embeddings_schema_rejects_legacy_column_set(db_session) -> None:
    """2026-08-14 二期段落化：validate 必须拒绝旧结构（列集合不匹配）"""
    import pytest

    from src.storage.vector_schema import validate_paragraph_embeddings_schema

    runtime_schema = db_session.execute(text("SELECT current_schema()")).scalar_one()
    db_session.execute(text(f"DROP TABLE IF EXISTS {runtime_schema}.paragraph_embeddings CASCADE"))
    db_session.execute(
        text(
            f"""
            CREATE TABLE {runtime_schema}.paragraph_embeddings (
                run_id VARCHAR(36) NOT NULL,
                chunk_id INTEGER NOT NULL,
                paragraph_index INTEGER NOT NULL,
                paragraph_text TEXT NOT NULL,
                embedding_vector vector(1024),
                created_at VARCHAR(50),
                PRIMARY KEY (run_id, chunk_id, paragraph_index)
            )
            """
        )
    )
    db_session.commit()

    with pytest.raises(ValueError, match="schema mismatch"):
        validate_paragraph_embeddings_schema(db_session)
