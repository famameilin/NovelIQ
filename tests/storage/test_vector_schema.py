from __future__ import annotations

from sqlalchemy import text

from src.config import settings
from src.storage.vector_schema import (
    ensure_paragraph_embeddings_schema,
    validate_paragraph_embeddings_schema,
)


def test_ensure_paragraph_embeddings_schema_creates_table_in_runtime_schema(db_session) -> None:
    """
    创建时间: 2026-04-24
    任务: level3-paragraph-rerank
    说明: paragraph_embeddings 应按当前 search_path 落到运行时 schema。
    """
    runtime_schema = db_session.execute(text("SELECT current_schema()")).scalar_one()
    db_session.execute(text(f"DROP TABLE IF EXISTS {runtime_schema}.paragraph_embeddings CASCADE"))
    db_session.commit()

    ensure_paragraph_embeddings_schema(db_session, settings.models.paragraph_embedding.embedding_dim)
    validate_paragraph_embeddings_schema(db_session, settings.models.paragraph_embedding.embedding_dim)

    table_regclass = db_session.execute(
        text("SELECT to_regclass(:table_name)"),
        {"table_name": f"{runtime_schema}.paragraph_embeddings"},
    ).scalar_one_or_none()
    assert table_regclass is not None

    columns = set(
        db_session.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = :schema_name
                  AND table_name = 'paragraph_embeddings'
                """
            ),
            {"schema_name": runtime_schema},
        ).scalars().all()
    )
    assert {"local_start_char", "local_end_char", "global_start_char", "global_end_char"} <= columns
    assert "start_char" not in columns
    assert "end_char" not in columns

    # 2026-08-13 P2：HNSW 向量索引已创建（语义检索不再全表扫描）
    hnsw_index = db_session.execute(
        text(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE schemaname = :schema_name
              AND tablename = 'paragraph_embeddings'
              AND indexdef ILIKE '%USING hnsw%embedding_vector%'
            """
        ),
        {"schema_name": runtime_schema},
    ).scalar_one_or_none()
    assert hnsw_index is not None
    assert "vector_cosine_ops" in hnsw_index
