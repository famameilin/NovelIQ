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


def _resolve_visible_table_schema(session: Session, table_name: str) -> str:
    """
    解析当前连接可见的目标表实际所在 schema。

    创建时间: 2026-04-22
    创建者: Codex
    任务: fix-preprocess-vector-schema-parent-resolution
    说明: `chunk_embeddings` 可能按当前运行时 schema 创建，
          但它依赖的 `chunks` / `analysis_runs` 在某些环境里未必和当前 schema 完全一致。
          这里按当前 search_path 实际能解析到的表，反查其真实 schema，避免手写 DDL 把父表误绑到错误空间。
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_name):
        raise ValueError(f"invalid table name: {table_name}")

    resolved_schema = session.execute(
        text(
            """
            SELECT n.nspname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.oid = to_regclass(:table_name)
            """
        ),
        {"table_name": table_name},
    ).scalar_one_or_none()
    if resolved_schema is None:
        raise ValueError(f"required table does not exist in current search_path: {table_name}")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", resolved_schema):
        raise ValueError(f"invalid schema name: {resolved_schema}")
    return resolved_schema


def ensure_chunk_embeddings_schema(session: Session, embedding_dim: int) -> None:
    """
    确保 `chunk_embeddings` 表在当前运行时 schema 下可用。

    创建时间: 2026-04-10
    创建者: TraeAI
    任务: implement-level3-vector-retrieval

    修改时间: 2026-04-22
    修改者: Codex
    任务: fix-preprocess-vector-schema-parent-resolution
    修改内容: 创建表时不再假设 `chunks` / `analysis_runs` 一定与当前 schema 同名同空间，
    而是按当前 search_path 解析父表真实 schema，避免预处理在隔离 schema 下创建外键时报 UndefinedTable。
    """
    if embedding_dim <= 0:
        raise ValueError(f"embedding dimension must be positive, got {embedding_dim}")

    runtime_schema = _resolve_runtime_schema(session)
    chunks_schema = _resolve_visible_table_schema(session, "chunks")
    analysis_runs_schema = _resolve_visible_table_schema(session, "analysis_runs")
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
                        REFERENCES {chunks_schema}.chunks(chunk_id, run_id) ON DELETE CASCADE,
                    FOREIGN KEY (run_id)
                        REFERENCES {analysis_runs_schema}.analysis_runs(run_id) ON DELETE CASCADE
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


def ensure_paragraph_embeddings_schema(session: Session, embedding_dim: int) -> None:
    """
    确保 `paragraph_embeddings` 表在当前运行时 schema 下可用。

    创建时间: 2026-04-24
    任务: level3-paragraph-rerank
    说明: paragraph embedding 只作为候选 chunk 内局部 rerank 数据源，
          表结构保留 chunk_id 与 chunk 内字符范围，方便回溯和 prompt 局部展示。

    修改时间: 2026-04-24
    任务: full-global-offset-rollout
    修改说明: 旧的 start_char/end_char 已替换为显式 local/global offset，
              直接升级 paragraph_embeddings 的字段合同，不保留旧歧义字段。
    """
    if embedding_dim <= 0:
        raise ValueError(f"embedding dimension must be positive, got {embedding_dim}")

    runtime_schema = _resolve_runtime_schema(session)
    chunks_schema = _resolve_visible_table_schema(session, "chunks")
    analysis_runs_schema = _resolve_visible_table_schema(session, "analysis_runs")
    session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    table_regclass = f"{runtime_schema}.paragraph_embeddings"
    table_exists = session.execute(text(f"SELECT to_regclass('{table_regclass}')")).scalar_one_or_none()

    required_offset_columns = {"local_start_char", "local_end_char", "global_start_char", "global_end_char"}
    existing_columns = _get_table_columns(session, "paragraph_embeddings") if table_exists is not None else set()
    if table_exists is not None and (
        "start_char" in existing_columns
        or "end_char" in existing_columns
        or not required_offset_columns.issubset(existing_columns)
    ):
        # 中文注释：用户已明确不需要兼容旧 paragraph offset 字段；
        # 发现旧结构时直接重建整张表，避免留下“列已半升级但约束/语义仍漂移”的状态。
        session.execute(text(f"DROP TABLE {runtime_schema}.paragraph_embeddings"))
        table_exists = None

    if table_exists is None:
        session.execute(
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
                    embedding_vector vector({embedding_dim}),
                    created_at VARCHAR(50),
                    PRIMARY KEY (run_id, chunk_id, paragraph_index),
                    FOREIGN KEY (chunk_id, run_id)
                        REFERENCES {chunks_schema}.chunks(chunk_id, run_id) ON DELETE CASCADE,
                    FOREIGN KEY (run_id)
                        REFERENCES {analysis_runs_schema}.analysis_runs(run_id) ON DELETE CASCADE
                )
                """
            )
        )
    else:
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
            f"ON {runtime_schema}.paragraph_embeddings USING btree (run_id)"
        )
    )
    session.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS idx_paragraph_embeddings_run_chunk "
            f"ON {runtime_schema}.paragraph_embeddings USING btree (run_id, chunk_id)"
        )
    )


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


def validate_paragraph_embeddings_schema(session: Session, embedding_dim: int) -> None:
    """
    校验 `paragraph_embeddings` 表与当前 embedding 维度一致。

    创建时间: 2026-04-24
    任务: level3-paragraph-rerank
    说明: Level3 paragraph rerank 依赖同一 embedding 模型维度，启动检查应显式失败而不是静默降级。

    修改时间: 2026-04-24
    任务: full-global-offset-rollout
    修改说明: 同步要求 global offset 列存在，避免新代码读取全文坐标时只在运行期晚失败。
    """
    if embedding_dim <= 0:
        raise ValueError(f"embedding dimension must be positive, got {embedding_dim}")

    runtime_schema = _resolve_runtime_schema(session)
    extension_exists = session.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).scalar_one_or_none()
    if extension_exists is None:
        raise ValueError("pgvector extension 'vector' is not installed")

    table_regclass = f"{runtime_schema}.paragraph_embeddings"
    table_exists = session.execute(text(f"SELECT to_regclass('{table_regclass}')")).scalar_one_or_none()
    if table_exists is None:
        raise ValueError("paragraph_embeddings table does not exist")

    vector_type = _get_embedding_vector_type(session, "paragraph_embeddings")
    expected_type = f"vector({embedding_dim})"
    if vector_type != expected_type:
        raise ValueError(
            "paragraph_embeddings.embedding_vector type mismatch: "
            f"expected {expected_type}, got {vector_type or 'unknown'}"
        )

    required_columns = {"local_start_char", "local_end_char", "global_start_char", "global_end_char"}
    existing_columns = _get_table_columns(session, "paragraph_embeddings")
    missing_columns = sorted(required_columns - existing_columns)
    if missing_columns:
        raise ValueError(
            "paragraph_embeddings missing required columns: "
            + ", ".join(missing_columns)
        )


def _get_chunk_embeddings_vector_type(session: Session) -> str | None:
    """
    获取 chunk embedding 向量列类型。

    修改时间: 2026-04-24
    任务: level3-paragraph-rerank
    修改说明: 保持旧函数名作为 chunk schema 调用入口，内部复用通用表类型查询。
    """
    return _get_embedding_vector_type(session, "chunk_embeddings")


def _get_embedding_vector_type(session: Session, table_name: str) -> str | None:
    """
    获取指定 embedding 表的向量列类型。

    创建时间: 2026-04-24
    任务: level3-paragraph-rerank
    说明: chunk_embeddings 与 paragraph_embeddings 共享同一列名与维度校验逻辑，
          这里统一封装，避免新增 paragraph schema 时复制 SQL。
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_name):
        raise ValueError(f"invalid table name: {table_name}")

    runtime_schema = _resolve_runtime_schema(session)
    return session.execute(
        text(
            """
            SELECT format_type(a.atttypid, a.atttypmod)
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = :schema_name
              AND c.relname = :table_name
              AND a.attname = 'embedding_vector'
              AND a.attnum > 0
              AND NOT a.attisdropped
            """
        ),
        {"schema_name": runtime_schema, "table_name": table_name},
    ).scalar_one_or_none()


def _get_table_columns(session: Session, table_name: str) -> set[str]:
    """
    获取当前运行时 schema 下表的列名集合。

    创建时间: 2026-04-24
    任务: full-global-offset-rollout
    说明: 在 validate 阶段显式校验新列是否存在，避免旧库只升级了部分 schema 就被误判为可用。
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_name):
        raise ValueError(f"invalid table name: {table_name}")

    runtime_schema = _resolve_runtime_schema(session)
    rows = session.execute(
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
    return {str(column_name) for column_name in rows}
