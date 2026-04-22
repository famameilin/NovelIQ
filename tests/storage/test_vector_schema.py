from __future__ import annotations

from sqlalchemy import text

from src.config import settings
from src.storage.vector_schema import ensure_chunk_embeddings_schema, validate_chunk_embeddings_schema


def test_ensure_chunk_embeddings_schema_creates_table_in_runtime_schema(db_session) -> None:
    """
    创建时间: 2026-04-22
    创建者: Codex
    任务: fix-preprocess-vector-schema-parent-resolution
    说明: 预处理阶段在测试隔离 schema 下补建 `chunk_embeddings` 时，
    不应再因为父表 schema 解析错误而失败；建表后 validate 也应能在当前运行时 schema 成功通过。
    """
    runtime_schema = db_session.execute(text("SELECT current_schema()")).scalar_one()
    db_session.execute(text(f"DROP TABLE IF EXISTS {runtime_schema}.chunk_embeddings CASCADE"))
    db_session.commit()

    ensure_chunk_embeddings_schema(db_session, settings.models.semantic_chunking.embedding_dim)
    validate_chunk_embeddings_schema(db_session, settings.models.semantic_chunking.embedding_dim)

    table_regclass = db_session.execute(
        text("SELECT to_regclass(:table_name)"),
        {"table_name": f"{runtime_schema}.chunk_embeddings"},
    ).scalar_one_or_none()
    assert table_regclass is not None
