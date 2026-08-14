from __future__ import annotations

from sqlalchemy import text

from src.config import settings
from src.storage.vector_schema import (
    ensure_paragraph_embeddings_schema,
    validate_paragraph_embeddings_schema,
)


def _table_columns(db_session, table_name: str) -> set[str]:
    runtime_schema = db_session.execute(text("SELECT current_schema()")).scalar_one()
    return set(
        db_session.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = :schema_name
                  AND table_name = :table_name
                """
            ),
            {"schema_name": runtime_schema, "table_name": table_name},
        ).scalars().all()
    )


def test_ensure_paragraph_embeddings_schema_creates_table_in_runtime_schema(db_session) -> None:
    """
    创建时间: 2026-04-24
    任务: level3-paragraph-rerank
    说明: paragraph_embeddings 应按当前 search_path 落到运行时 schema。

    2026-08-14 二期段落化（§5.2）：新结构只保留段落身份与向量溯源列，
    旧列（chunk_id/paragraph_index/paragraph_text/local/global 坐标）全部移除。
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

    columns = _table_columns(db_session, "paragraph_embeddings")
    assert {
        "run_id",
        "paragraph_id",
        "embedding_vector",
        "embedding_model_key",
        "embedding_dimension",
        "source_content_hash",
        "created_at",
    } <= columns
    # 旧列全部移除
    for legacy_column in (
        "chunk_id",
        "paragraph_index",
        "paragraph_text",
        "local_start_char",
        "local_end_char",
        "global_start_char",
        "global_end_char",
        "start_char",
        "end_char",
    ):
        assert legacy_column not in columns

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

    # (run_id) 索引保留；旧复合索引 (run_id, chunk_id) 已随旧结构移除
    run_id_index = db_session.execute(
        text(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE schemaname = :schema_name
              AND tablename = 'paragraph_embeddings'
              AND indexdef ILIKE '%idx_paragraph_embeddings_run_id%'
            """
        ),
        {"schema_name": runtime_schema},
    ).scalar_one_or_none()
    assert run_id_index is not None
    assert "chunk_id" not in run_id_index


def test_ensure_paragraph_embeddings_schema_rebuilds_incompatible_legacy_structure(db_session) -> None:
    """
    2026-08-14 二期段落化（§5.2）：旧结构（一期段落 embedding 列集）与现结构
    不兼容，ensure 检测到列集合不匹配时 DROP TABLE 后按新结构重建（数据不回填）。
    """
    runtime_schema = db_session.execute(text("SELECT current_schema()")).scalar_one()
    db_session.execute(text(f"DROP TABLE IF EXISTS {runtime_schema}.paragraph_embeddings CASCADE"))
    # 构造一期旧结构（含 paragraph_text/local/global 坐标冗余列）
    db_session.execute(
        text(
            f"""
            CREATE TABLE {runtime_schema}.paragraph_embeddings (
                run_id VARCHAR(36) NOT NULL,
                chunk_id INTEGER NOT NULL,
                paragraph_index INTEGER NOT NULL,
                paragraph_text TEXT NOT NULL,
                local_start_char INTEGER NOT NULL,
                local_end_char INTEGER NOT NULL,
                global_start_char INTEGER NOT NULL,
                global_end_char INTEGER NOT NULL,
                embedding_vector vector(1024),
                created_at VARCHAR(50),
                PRIMARY KEY (run_id, chunk_id, paragraph_index)
            )
            """
        )
    )
    db_session.execute(
        text(
            f"INSERT INTO {runtime_schema}.paragraph_embeddings "
            "(run_id, chunk_id, paragraph_index, paragraph_text, local_start_char, "
            "local_end_char, global_start_char, global_end_char, embedding_vector) "
            "VALUES ('run-legacy', 0, 0, '旧段落', 0, 3, 0, 3, "
            "'["
            + ",".join(["0.1"] * 1024)
            + "]'::vector)"
        )
    )
    db_session.commit()

    ensure_paragraph_embeddings_schema(db_session, 1024)
    validate_paragraph_embeddings_schema(db_session, 1024)

    columns = _table_columns(db_session, "paragraph_embeddings")
    assert "paragraph_id" in columns
    # 旧列随 DROP 重建移除
    assert "chunk_id" not in columns
    assert "paragraph_index" not in columns
    assert "paragraph_text" not in columns
    # 旧数据不回填
    legacy_count = db_session.execute(
        text(
            f"SELECT count(*) FROM {runtime_schema}.paragraph_embeddings "
            "WHERE run_id = 'run-legacy'"
        )
    ).scalar_one()
    assert legacy_count == 0
    # 旧结构外键（指向 chunks）消失，新结构外键指向 paragraphs/analysis_runs
    # （regclass 文本输出按 search_path 解析为未限定表名）
    fk_targets = {
        str(value).replace('"', "")
        for value in db_session.execute(
            text(
                """
                SELECT confrelid::regclass::text
                FROM pg_constraint
                WHERE conrelid = to_regclass(:table_name)
                  AND contype = 'f'
                """
            ),
            {"table_name": f"{runtime_schema}.paragraph_embeddings"},
        ).scalars().all()
    }
    assert fk_targets == {"paragraphs", "analysis_runs"}
    assert "chunks" not in fk_targets


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
        validate_paragraph_embeddings_schema(db_session, 1024)
