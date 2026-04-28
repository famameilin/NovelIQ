"""
说明: PostgreSQL 数据库引擎与 Session 管理，使用 SQLAlchemy

本模块提供：
- get_engine(): 获取 SQLAlchemy 引擎（单例）
- SessionLocal: Session 工厂类
- get_session(): 上下文管理器，用于获取 Session
- init_db(): 初始化数据库（创建所有表）
"""

from __future__ import annotations

import os
import re
from collections.abc import Generator
from contextlib import contextmanager

from loguru import logger
from sqlalchemy import Connection, Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

_engine: Engine | None = None
_session_factory: sessionmaker | None = None


def get_database_url() -> str:
    """
    获取数据库连接 URL

    优先级：
    1. DATABASE_URL 环境变量
    2. 抛出异常

    Returns:
        数据库连接 URL 字符串
    """
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "Please set it to your PostgreSQL connection string, e.g., "
            "postgresql://user:password@localhost:5432/dbname"
        )
    return database_url


def get_database_schema() -> str | None:
    """
    获取数据库 schema 名称。

    说明: 运行时默认不指定 schema；
          测试环境可通过 DATABASE_SCHEMA 把所有未限定表名收敛到独立 schema。
    """
    schema = os.environ.get("DATABASE_SCHEMA")
    if not schema:
        return None
    normalized = schema.strip()
    if not normalized:
        return None
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", normalized):
        raise RuntimeError(f"Invalid DATABASE_SCHEMA: {schema}")
    return normalized


def get_engine():
    """
    获取 SQLAlchemy 引擎（单例模式）

    说明: 单例模式获取数据库引擎，支持连接池配置

    Returns:
        SQLAlchemy Engine 实例
    """
    global _engine

    if _engine is not None:
        return _engine

    database_url = get_database_url()

    pool_size = int(os.environ.get("DB_POOL_SIZE", "5"))
    max_overflow = int(os.environ.get("DB_MAX_OVERFLOW", "10"))
    pool_timeout = int(os.environ.get("DB_POOL_TIMEOUT", "30"))
    pool_recycle = int(os.environ.get("DB_POOL_RECYCLE", "1800"))
    connect_timeout = int(os.environ.get("DB_CONNECT_TIMEOUT", "5"))
    statement_timeout = int(os.environ.get("DB_STATEMENT_TIMEOUT", "30000"))
    echo = os.environ.get("DB_ECHO", "false").lower() == "true"
    database_schema = get_database_schema()

    option_parts = [f"-c statement_timeout={statement_timeout}"]
    if database_schema:
        option_parts.append(f"-c search_path={database_schema},public")

    connect_args = {
        "connect_timeout": connect_timeout,
        "options": " ".join(option_parts),
    }

    _engine = create_engine(
        database_url,
        poolclass=QueuePool,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
        pool_pre_ping=True,
        echo=echo,
        connect_args=connect_args,
    )

    if database_url.startswith("postgresql"):

        @event.listens_for(_engine, "connect")
        def set_postgresql_settings(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("SET TIME ZONE 'UTC'")
            if database_schema:
                # 连接池里的连接被复用时，仍要确保 search_path 固定在当前运行时 schema，
                # 避免测试并发时把 ORM/原生 SQL 混写回 public 或其他进程的隔离空间。
                cursor.execute(f"SET search_path TO {database_schema}, public")
            cursor.close()

    @event.listens_for(_engine, "checkout")
    def on_checkout(dbapi_conn, conn_record, conn_proxy):
        if _engine is not None:
            logger.debug(f"Pool checkout: active={_engine.pool.status()}")

    @event.listens_for(_engine, "checkin")
    def on_checkin(dbapi_conn, conn_record):
        if _engine is not None:
            logger.debug(f"Pool checkin: active={_engine.pool.status()}")

    logger.info(
        f"Created SQLAlchemy engine for {database_url.split(':')[0]} "
        f"(pool_size={pool_size}, connect_timeout={connect_timeout}s, "
        f"statement_timeout={statement_timeout}ms)"
    )

    return _engine


def get_session_factory() -> sessionmaker:
    """
    获取 Session 工厂（单例模式）

    说明: 返回 Session 工厂类，用于创建 Session

    Returns:
        sessionmaker 实例
    """
    global _session_factory

    if _session_factory is not None:
        return _session_factory

    engine = get_engine()
    _session_factory = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )

    return _session_factory


SessionLocal = get_session_factory


def _constraint_exists(connection: Connection, table_name: str, constraint_name: str) -> bool:
    """
    检查当前 schema 下是否已存在指定约束。

    说明: 运行时补约束前必须先做显式存在性检查，
          避免旧库增量迁移与新库 create_all 在启动时互相撞重复 DDL。
    """
    return bool(
        connection.execute(
            text(
                """
                SELECT 1
                FROM information_schema.table_constraints
                WHERE table_schema = current_schema()
                  AND table_name = :table_name
                  AND constraint_name = :constraint_name
                LIMIT 1
                """
            ),
            {"table_name": table_name, "constraint_name": constraint_name},
        ).scalar_one_or_none()
    )


def _table_exists(connection: Connection, table_name: str) -> bool:
    """
    检查当前 schema 下是否存在指定表。
    """

    return bool(
        connection.execute(
            text(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = :table_name
                LIMIT 1
                """
            ),
            {"table_name": table_name},
        ).scalar_one_or_none()
    )


def _get_table_columns(connection: Connection, table_name: str) -> set[str]:
    """
    说明: 启动期需要对关键表做正式合同校验，这里统一读取当前 schema 下的列集合，
    避免后续把“旧表还能跑”误当成可接受状态。
    """

    rows = connection.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = :table_name
            """
        ),
        {"table_name": table_name},
    ).fetchall()
    return {str(row.column_name) for row in rows}


def _assert_no_orphans(connection: Connection, sql: str, *, context: str) -> None:
    """
    在补外键前校验目标子表没有孤儿数据。

    说明: 当前仓库不接受“发现脏数据但继续跳过”的静默策略；
          若仍有孤儿行，直接抛错阻止把不一致状态带入更深处。
    """
    orphan_count = int(connection.execute(text(sql)).scalar_one())
    if orphan_count > 0:
        raise RuntimeError(f"Cannot add foreign key for {context}: found {orphan_count} orphan row(s)")


def _normalize_analysis_related_novel_ids(connection: Connection) -> None:
    """
    基于 analysis_runs 回填历史表里漂移的 novel_id。

    说明: `cloud_analysis` / `token_usage` / `chunk_locations` 的 novel_id
          实际是 run 侧信息的冗余镜像；补外键前先对齐到 analysis_runs，
          可以安全修复历史 `unknown` 或旧值漂移，而不需要删数据。
    """
    statements = [
        """
        UPDATE cloud_analysis AS child
        SET novel_id = parent.novel_id
        FROM analysis_runs AS parent
        WHERE child.run_id = parent.run_id
          AND child.novel_id IS DISTINCT FROM parent.novel_id
        """,
        """
        UPDATE token_usage AS child
        SET novel_id = parent.novel_id
        FROM analysis_runs AS parent
        WHERE child.run_id = parent.run_id
          AND child.novel_id IS DISTINCT FROM parent.novel_id
        """,
        """
        UPDATE chunk_locations AS child
        SET novel_id = parent.novel_id
        FROM analysis_runs AS parent
        WHERE child.run_id = parent.run_id
          AND child.novel_id IS DISTINCT FROM parent.novel_id
        """,
    ]

    for statement in statements:
        connection.execute(text(statement))


def _ensure_analysis_related_foreign_keys(connection: Connection) -> None:
    """
    为历史 PostgreSQL 表补齐分析链路缺失的外键约束。

    说明: 这批约束都属于“旧库缺失、新库 ORM 已声明”的收口项。
          先做可安全回填的 novel_id 对齐，再显式校验孤儿数据，最后补约束。
          其中 analysis_runs.novel_id 是整条分析链路的父约束，必须一并补齐，
          否则旧库仍能继续写入悬空 novel_id。
    """
    _normalize_analysis_related_novel_ids(connection)

    constraint_specs = [
        {
            "table": "analysis_runs",
            "name": "analysis_runs_novel_id_fkey",
            "ddl": (
                "ALTER TABLE analysis_runs "
                "ADD CONSTRAINT analysis_runs_novel_id_fkey "
                "FOREIGN KEY (novel_id) REFERENCES novels(novel_id) ON DELETE RESTRICT"
            ),
            "orphan_check": (
                "SELECT COUNT(*) FROM analysis_runs child "
                "LEFT JOIN novels parent ON parent.novel_id = child.novel_id "
                "WHERE parent.novel_id IS NULL"
            ),
            "context": "analysis_runs.novel_id -> novels.novel_id",
        },
        {
            "table": "disambig_checkpoint",
            "name": "disambig_checkpoint_run_id_fkey",
            "ddl": (
                "ALTER TABLE disambig_checkpoint "
                "ADD CONSTRAINT disambig_checkpoint_run_id_fkey "
                "FOREIGN KEY (run_id) REFERENCES analysis_runs(run_id) ON DELETE CASCADE"
            ),
            "orphan_check": (
                "SELECT COUNT(*) FROM disambig_checkpoint child "
                "LEFT JOIN analysis_runs parent ON parent.run_id = child.run_id "
                "WHERE parent.run_id IS NULL"
            ),
            "context": "disambig_checkpoint.run_id -> analysis_runs.run_id",
        },
        {
            "table": "chunk_locations",
            "name": "chunk_locations_chunk_id_run_id_fkey",
            "ddl": (
                "ALTER TABLE chunk_locations "
                "ADD CONSTRAINT chunk_locations_chunk_id_run_id_fkey "
                "FOREIGN KEY (chunk_id, run_id) REFERENCES chunks(chunk_id, run_id) ON DELETE CASCADE"
            ),
            "orphan_check": (
                "SELECT COUNT(*) FROM chunk_locations child "
                "LEFT JOIN chunks parent "
                "ON parent.chunk_id = child.chunk_id AND parent.run_id = child.run_id "
                "WHERE parent.run_id IS NULL"
            ),
            "context": "chunk_locations.(chunk_id, run_id) -> chunks.(chunk_id, run_id)",
        },
        {
            "table": "chunk_locations",
            "name": "chunk_locations_novel_id_fkey",
            "ddl": (
                "ALTER TABLE chunk_locations "
                "ADD CONSTRAINT chunk_locations_novel_id_fkey "
                "FOREIGN KEY (novel_id) REFERENCES novels(novel_id) ON DELETE RESTRICT"
            ),
            "orphan_check": (
                "SELECT COUNT(*) FROM chunk_locations child "
                "LEFT JOIN novels parent ON parent.novel_id = child.novel_id "
                "WHERE parent.novel_id IS NULL"
            ),
            "context": "chunk_locations.novel_id -> novels.novel_id",
        },
        {
            "table": "cloud_analysis",
            "name": "cloud_analysis_novel_id_fkey",
            "ddl": (
                "ALTER TABLE cloud_analysis "
                "ADD CONSTRAINT cloud_analysis_novel_id_fkey "
                "FOREIGN KEY (novel_id) REFERENCES novels(novel_id) ON DELETE RESTRICT"
            ),
            "orphan_check": (
                "SELECT COUNT(*) FROM cloud_analysis child "
                "LEFT JOIN novels parent ON parent.novel_id = child.novel_id "
                "WHERE child.novel_id IS NOT NULL AND parent.novel_id IS NULL"
            ),
            "context": "cloud_analysis.novel_id -> novels.novel_id",
        },
        {
            "table": "global_context",
            "name": "global_context_novel_id_fkey",
            "ddl": (
                "ALTER TABLE global_context "
                "ADD CONSTRAINT global_context_novel_id_fkey "
                "FOREIGN KEY (novel_id) REFERENCES novels(novel_id) ON DELETE RESTRICT"
            ),
            "orphan_check": (
                "SELECT COUNT(*) FROM global_context child "
                "LEFT JOIN novels parent ON parent.novel_id = child.novel_id "
                "WHERE parent.novel_id IS NULL"
            ),
            "context": "global_context.novel_id -> novels.novel_id",
        },
        {
            "table": "graph_relation_events",
            "name": "graph_relation_events_chunk_id_run_id_fkey",
            "ddl": (
                "ALTER TABLE graph_relation_events "
                "ADD CONSTRAINT graph_relation_events_chunk_id_run_id_fkey "
                "FOREIGN KEY (chunk_id, run_id) REFERENCES chunks(chunk_id, run_id) ON DELETE CASCADE"
            ),
            "orphan_check": (
                "SELECT COUNT(*) FROM graph_relation_events child "
                "LEFT JOIN chunks parent "
                "ON parent.chunk_id = child.chunk_id AND parent.run_id = child.run_id "
                "WHERE parent.run_id IS NULL"
            ),
            "context": "graph_relation_events.(chunk_id, run_id) -> chunks.(chunk_id, run_id)",
        },
        {
            "table": "token_usage",
            "name": "token_usage_novel_id_fkey",
            "ddl": (
                "ALTER TABLE token_usage "
                "ADD CONSTRAINT token_usage_novel_id_fkey "
                "FOREIGN KEY (novel_id) REFERENCES novels(novel_id) ON DELETE RESTRICT"
            ),
            "orphan_check": (
                "SELECT COUNT(*) FROM token_usage child "
                "LEFT JOIN novels parent ON parent.novel_id = child.novel_id "
                "WHERE parent.novel_id IS NULL"
            ),
            "context": "token_usage.novel_id -> novels.novel_id",
        },
    ]

    for spec in constraint_specs:
        if _constraint_exists(connection, spec["table"], spec["name"]):
            continue
        _assert_no_orphans(connection, spec["orphan_check"], context=spec["context"])
        connection.execute(text(spec["ddl"]))


def _ensure_runtime_schema(engine: Engine) -> None:
    """
    为历史 PostgreSQL 表补齐运行时需要的非破坏性 schema。

    说明: 当前项目仍以 create_all 为主，旧库不会自动跟随 ORM 演进。
          这里仅做“补列 / 补索引”这类非破坏性修复，不在应用启动时静默删除列或重建约束。
    """
    dialect_name = getattr(getattr(engine, "dialect", None), "name", "")
    if dialect_name != "postgresql":
        return

    statements = [
        "ALTER TABLE model_interactions ADD COLUMN IF NOT EXISTS reasoning_tokens INTEGER",
        "ALTER TABLE model_interactions ADD COLUMN IF NOT EXISTS thinking_state VARCHAR(20) NOT NULL DEFAULT 'unknown'",
        "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS char_end_offset INTEGER",
        "ALTER TABLE cloud_analysis ADD COLUMN IF NOT EXISTS foreshadow_expectation DOUBLE PRECISION",
        "ALTER TABLE chunk_annotation ADD COLUMN IF NOT EXISTS setup_summary TEXT",
        "ALTER TABLE chunk_annotation ADD COLUMN IF NOT EXISTS payoff_likelihood VARCHAR(20)",
        "ALTER TABLE chunk_annotation ADD COLUMN IF NOT EXISTS linked_setup_id VARCHAR(36)",
        "ALTER TABLE chunk_foreshadowing ADD COLUMN IF NOT EXISTS setup_summary TEXT",
        "ALTER TABLE chunk_foreshadowing ADD COLUMN IF NOT EXISTS payoff_likelihood VARCHAR(20)",
        "ALTER TABLE chunk_foreshadowing ADD COLUMN IF NOT EXISTS is_new_setup INTEGER",
        "ALTER TABLE chunk_foreshadowing ADD COLUMN IF NOT EXISTS linked_setup_id VARCHAR(36)",
        "ALTER TABLE chunk_foreshadowing ADD COLUMN IF NOT EXISTS setup_status VARCHAR(30)",
        "CREATE INDEX IF NOT EXISTS idx_chunk_curves_run_id ON chunk_curves (run_id)",
        (
            "CREATE INDEX IF NOT EXISTS idx_foreshadowing_threads_run_active_last_chunk "
            "ON foreshadowing_threads (run_id, active, last_chunk_id)"
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_foreshadowing_thread_hits_run_chunk "
            "ON foreshadowing_thread_hits (run_id, chunk_id)"
        ),
    ]

    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
        if _table_exists(conn, "chunk_embeddings"):
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_run_id ON chunk_embeddings (run_id)"))
        _ensure_analysis_related_foreign_keys(conn)


def _assert_focus_contract_schema(engine: Engine) -> None:
    """
    说明: 本次主角合同重构明确不兼容旧库，因此启动时必须显式检查
    `cloud_analysis` 是否已切到焦点合同；若仍停留在旧 `protagonist` 结构，直接阻断启动。
    """
    dialect_name = getattr(getattr(engine, "dialect", None), "name", "")
    if dialect_name != "postgresql":
        return

    with engine.begin() as conn:
        if not _table_exists(conn, "cloud_analysis"):
            return

        actual_columns = _get_table_columns(conn, "cloud_analysis")
        required_columns = {
            "focus_structure",
            "focus_characters",
            "main_characters",
            "core_cast",
        }
        missing_columns = sorted(required_columns - actual_columns)
        if missing_columns:
            raise RuntimeError(
                "cloud_analysis is missing focus contract columns: "
                f"{missing_columns}. Please recreate or manually migrate the current database schema "
                "so that `cloud_analysis` includes the full focus-contract column set before starting the service."
            )

        if "protagonist" in actual_columns:
            raise RuntimeError(
                "cloud_analysis still contains legacy column `protagonist`. "
                "Please recreate or manually migrate the current database schema "
                "to remove legacy protagonist-contract columns before starting the service."
            )


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    获取 Session 的上下文管理器

    说明: 提供上下文管理器方式获取 Session，自动处理提交和回滚

    Yields:
        SQLAlchemy Session 实例

    注意:
        - 退出上下文时会自动调用 commit()
        - 对于只读操作（如 SELECT），commit 是无害的空操作
        - 如需显式控制事务，请在上下文内调用 session.rollback() 或 session.commit()

    使用示例:
        with get_session() as session:
            session.execute(text("SELECT 1"))
            session.commit()
    """
    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(include_level3_tables: bool = False) -> None:
    """
    初始化数据库（创建所有表）

    说明: 使用 ORM 模型创建所有数据库表

    注意：生产环境推荐使用 Alembic 迁移
    """
    from src.storage.models import Base

    engine = get_engine()
    tables = list(Base.metadata.sorted_tables)
    if not include_level3_tables:
        # Level3 的 pgvector 表由 preprocess 按需 ensure；
        # 普通启动不主动创建，避免未启用 RAG 的环境被向量扩展约束牵连。
        tables = [table for table in tables if table.name not in {"chunk_embeddings", "paragraph_embeddings"}]
    Base.metadata.create_all(bind=engine, tables=tables)
    _ensure_runtime_schema(engine)
    _assert_focus_contract_schema(engine)
    logger.info("Database tables created successfully")


def dispose_engine() -> None:
    """
    释放数据库引擎资源

    说明: 用于测试或应用关闭时清理资源
    """
    global _engine, _session_factory

    if _engine is not None:
        _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("SQLAlchemy engine disposed")


def get_pool_status() -> dict | None:
    """
    获取连接池状态

    说明: 返回连接池状态信息，用于监控和调试

    Returns:
        包含连接池状态的字典，如果引擎未初始化则返回 None
    """
    if _engine is None:
        return None

    pool = _engine.pool
    if not isinstance(pool, QueuePool):
        return {
            "pool_size": 0,
            "checked_in": 0,
            "checked_out": 0,
            "overflow": 0,
            "invalid": 0,
        }

    invalidated_count_attr = getattr(pool, "invalidatedcount", None)
    invalidated_count = int(invalidated_count_attr()) if callable(invalidated_count_attr) else 0
    return {
        "pool_size": pool.size(),
        "checked_in": pool.checkedin(),
        "checked_out": pool.checkedout(),
        "overflow": pool.overflow(),
        "invalid": invalidated_count,
    }
