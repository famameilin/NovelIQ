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
from typing import Any

from loguru import logger
from sqlalchemy import Connection, Engine, create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, QueuePool

from src.storage.database_url import resolve_database_url_from_env

_engine: Engine | None = None
_session_factory: sessionmaker | None = None


def get_database_url() -> str:
    """
    获取数据库连接 URL

    优先级：
    1. DATABASE JSON 环境对象
    2. 抛出异常

    Returns:
        数据库连接 URL 字符串
    """
    return resolve_database_url_from_env("DATABASE")


def get_database_schema() -> str | None:
    """
    获取数据库 schema 名称

    说明: 运行时默认不指定 schema；
          测试环境可通过 DATABASE_SCHEMA 把所有未限定表名收敛到独立 schema
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


def _database_name_from_url(database_url: str) -> str | None:
    """2026-08-08 用于从 SQLAlchemy URL 解析目标数据库名称"""
    if not database_url.startswith("postgresql"):
        return None
    url = make_url(database_url)
    database = url.database
    if not database:
        return None
    return database


def _admin_database_url(database_url: str) -> str:
    """2026-08-08 用于把目标库 URL 指向默认 postgres 库以执行建库 DDL"""
    return make_url(database_url).set(database="postgres").render_as_string(
        hide_password=False
    )


def _safe_identifier(name: str) -> bool:
    """2026-08-08 用于限制自动建库标识符为 PostgreSQL 安全格式"""
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", name))


def ensure_database_exists() -> None:
    """2026-08-08 用于首次启动时自动创建缺失的目标数据库"""
    if os.environ.get("DB_AUTO_CREATE_DATABASE", "true").lower() != "true":
        return
    database_url = get_database_url()
    database_name = _database_name_from_url(database_url)
    if database_name is None or not _safe_identifier(database_name):
        return
    admin_engine: Any = None
    try:
        admin_engine = create_engine(
            _admin_database_url(database_url),
            poolclass=NullPool,
            isolation_level="AUTOCOMMIT",
            connect_args={"connect_timeout": int(os.environ.get("DB_CONNECT_TIMEOUT", "5"))},
        )
        with admin_engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": database_name},
            ).scalar_one_or_none()
            if exists:
                return
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
            logger.info("Auto-created missing database: {}", database_name)
    except OperationalError as exc:
        logger.warning(
            "Failed to auto-create database {}: {}; startup will retry direct connection",
            database_name,
            exc,
        )
    finally:
        if admin_engine is not None:
            admin_engine.dispose()


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
                # 避免测试并发时把 ORM/原生 SQL 混写回 public 或其他进程的隔离空间
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
    检查当前 schema 下是否已存在指定约束

    说明: 运行时补约束前必须先做显式存在性检查，
          避免旧库增量迁移与新库 create_all 在启动时互相撞重复 DDL
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
    检查当前 schema 下是否存在指定表
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
    避免后续把“旧表还能跑”误当成可接受状态
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
    在补外键前校验目标子表没有孤儿数据

    说明: 当前仓库不接受“发现脏数据但继续跳过”的静默策略；
          若仍有孤儿行，直接抛错阻止把不一致状态带入更深处
    """
    orphan_count = int(connection.execute(text(sql)).scalar_one())
    if orphan_count > 0:
        raise RuntimeError(f"Cannot add foreign key for {context}: found {orphan_count} orphan row(s)")


def _normalize_analysis_related_novel_ids(connection: Connection) -> None:
    """
    基于 analysis_runs 回填历史表里漂移的 novel_id

    说明: `cloud_analysis` / `token_usage` 的 novel_id
          实际是 run 侧信息的冗余镜像；补外键前先对齐到 analysis_runs，
          可以安全修复历史 `unknown` 或旧值漂移，而不需要删数据
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
    ]

    for statement in statements:
        connection.execute(text(statement))


def _ensure_analysis_related_foreign_keys(connection: Connection) -> None:
    """
    为历史 PostgreSQL 表补齐分析链路缺失的外键约束

    说明: 这批约束都属于“旧库缺失、新库 ORM 已声明”的收口项
          先做可安全回填的 novel_id 对齐，再显式校验孤儿数据，最后补约束
          其中 analysis_runs.novel_id 是整条分析链路的父约束，必须一并补齐，
          否则旧库仍能继续写入悬空 novel_id
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
    修改时间: 2026-04-30
    任务: diagnosis-latest-only-reference-contract
    修改原因: `cloud_analysis` 不再依赖 reference_contract_version 补列；启动期只补仍在使用的业务列。

    为历史 PostgreSQL 表补齐运行时需要的非破坏性 schema

    说明: 当前项目仍以 create_all 为主，旧库不会自动跟随 ORM 演进
          这里仅做“补列 / 补索引”这类非破坏性修复，不在应用启动时静默删除列或重建约束
    """
    dialect_name = getattr(getattr(engine, "dialect", None), "name", "")
    if dialect_name != "postgresql":
        return

    statements = [
        "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS char_end_offset INTEGER",
        "ALTER TABLE cloud_analysis ADD COLUMN IF NOT EXISTS foreshadow_expectation DOUBLE PRECISION",
        "ALTER TABLE cloud_analysis ADD COLUMN IF NOT EXISTS genre_labels TEXT",
        "ALTER TABLE cloud_analysis ADD COLUMN IF NOT EXISTS style_labels TEXT",
        "ALTER TABLE foreshadowing_threads ADD COLUMN IF NOT EXISTS confidence VARCHAR(20) NOT NULL DEFAULT 'high'",
        "ALTER TABLE graph_entities ADD COLUMN IF NOT EXISTS attributes JSONB NOT NULL DEFAULT '{}'::jsonb",
        (
            "ALTER TABLE case_resolution_mappings "
            "ADD COLUMN IF NOT EXISTS target_dialogue_id VARCHAR(64)"
        ),
        (
            "ALTER TABLE case_resolution_mappings "
            "ADD COLUMN IF NOT EXISTS target_setup_id VARCHAR(36)"
        ),
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
        _ensure_analysis_related_foreign_keys(conn)


def _create_graph_read_views(engine: Engine) -> None:
    """2026-08-07 用于创建章节版本图的当前状态关系与参与统计只读视图"""
    dialect_name = getattr(getattr(engine, "dialect", None), "name", "")
    if dialect_name != "postgresql":
        return

    statements = [
        """
        CREATE OR REPLACE VIEW entity_state_current AS
        SELECT DISTINCT ON (state_row.run_id, state_row.entity_id)
            state_row.state_version_id,
            state_row.graph_version_id,
            state_row.run_id,
            state_row.chapter_id,
            state_row.entity_id,
            state_row.state_revision,
            state_row.state,
            state_row.changes,
            state_row.created_at
        FROM entity_state_versions AS state_row
        JOIN graph_versions AS version_row
          ON version_row.graph_version_id = state_row.graph_version_id
        ORDER BY
            state_row.run_id,
            state_row.entity_id,
            version_row.chapter_order DESC,
            state_row.state_revision DESC
        """,
        """
        CREATE OR REPLACE VIEW graph_relations_current AS
        SELECT latest.*
        FROM (
            SELECT DISTINCT ON (version_row.run_id, version_row.relation_id)
                version_row.relation_version_id,
                version_row.graph_version_id,
                version_row.run_id,
                version_row.chapter_id,
                version_row.relation_id,
                version_row.relation_revision,
                version_row.relation_type,
                version_row.attributes,
                version_row.is_active,
                version_row.changes,
                version_row.created_at
            FROM graph_relation_versions AS version_row
            JOIN graph_versions AS graph_version
              ON graph_version.graph_version_id = version_row.graph_version_id
            ORDER BY
                version_row.run_id,
                version_row.relation_id,
                graph_version.chapter_order DESC,
                version_row.relation_revision DESC
        ) AS latest
        WHERE latest.is_active
        """,
        """
        CREATE OR REPLACE VIEW graph_entity_participants AS
        SELECT
            entity_row.run_id,
            entity_row.entity_id,
            COUNT(current_relation.relation_id)::INTEGER AS current_degree,
            MIN(version_row.chapter_order) AS first_relation_chapter_order,
            MAX(version_row.chapter_order) AS last_relation_chapter_order
        FROM graph_entities AS entity_row
        LEFT JOIN graph_relations AS relation_row
          ON relation_row.run_id = entity_row.run_id
         AND (
             relation_row.from_entity_id = entity_row.entity_id
             OR relation_row.to_entity_id = entity_row.entity_id
         )
        LEFT JOIN graph_relations_current AS current_relation
          ON current_relation.run_id = relation_row.run_id
         AND current_relation.relation_id = relation_row.relation_id
        LEFT JOIN graph_versions AS version_row
          ON version_row.graph_version_id = current_relation.graph_version_id
        GROUP BY entity_row.run_id, entity_row.entity_id
        """,
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _assert_focus_contract_schema(engine: Engine) -> None:
    """
    修改时间: 2026-04-30
    任务: diagnosis-latest-only-reference-contract
    修改原因: latest-only 之后只校验真实焦点合同列，不再把 reference_contract_version 当成启动前置条件。

    说明: 本次主角合同重构明确不兼容旧库，因此启动时必须显式检查
    `cloud_analysis` 是否已切到焦点合同；若仍停留在旧 `protagonist` 结构，直接阻断启动
    """
    dialect_name = getattr(getattr(engine, "dialect", None), "name", "")
    if dialect_name != "postgresql":
        return

    with engine.begin() as conn:
        if not _table_exists(conn, "cloud_analysis"):
            return

        actual_columns = _get_table_columns(conn, "cloud_analysis")
        required_columns = {
            "genre_labels",
            "style_labels",
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

        if "narrative_type" in actual_columns:
            raise RuntimeError(
                "cloud_analysis still contains legacy column `narrative_type`. "
                "Please recreate or manually migrate the current database schema "
                "to remove legacy narrative type columns before starting the service."
            )


def _assert_annotation_contract_schema(engine: Engine) -> None:
    """2026-08-07 用于阻止旧合同列继续承载新语义写入标注"""
    dialect_name = getattr(getattr(engine, "dialect", None), "name", "")
    if dialect_name != "postgresql":
        return

    required_columns = {
        "chapter_annotations": {
            "annotation_id",
            "run_id",
            "chapter_id",
            "payload",
            "created_at",
        },
        "dialogue_records": {
            "dialogue_id",
            "run_id",
            "chunk_id",
            "chapter_id",
            "candidate_key",
            "content",
            "start",
            "end",
            "speaker",
            "tone",
            "is_inner_monologue",
            "confidence",
        },
        "case_pool_cases": {
            "id",
            "run_id",
            "type",
            "chunk_id",
            "keys",
            "description",
            "target_key",
            "target_ref",
            "state",
            "created_by_annotation_id",
        },
        "case_resolution_mappings": {
            "mapping_id",
            "run_id",
            "annotation_id",
            "case_id",
            "type",
            "target_ref",
            "resolution",
            "target_fact_id",
            "target_fact_revision",
            "target_dialogue_id",
            "target_setup_id",
        },
    }
    legacy_columns = {
        "chapter_annotations": {
            "initial_finish_payload",
            "revision_payload",
        },
    }
    with engine.begin() as connection:
        for table_name, required in required_columns.items():
            if not _table_exists(connection, table_name):
                continue
            actual = _get_table_columns(connection, table_name)
            missing = sorted(required - actual)
            if missing:
                raise RuntimeError(
                    f"{table_name} is missing annotation contract columns: {missing}. "
                    "Please recreate or explicitly migrate the continuity tables before starting the service."
                )
            leftover = sorted(
                legacy_columns.get(table_name, set()) & actual
            )
            if leftover:
                raise RuntimeError(
                    f"{table_name} still contains legacy annotation contract columns: {leftover}. "
                    "Please drop the legacy columns or recreate the tables before starting the service."
                )


def _assert_agent_audit_contract_schema(engine: Engine) -> None:
    """
    2026-08-10 用于阻止旧审计库直接启动

    说明: 本次审计重构不兼容旧库：model_interactions 必须已删除、
    agent_invocations/agent_turns/agent_tool_calls 必须存在、
    token_usage 必须已按新结构重建。不增加运行时兼容建表分支，
    旧库未执行新 DDL 时直接启动失败。
    """
    dialect_name = getattr(getattr(engine, "dialect", None), "name", "")
    if dialect_name != "postgresql":
        return

    required_tables = {
        "agent_invocations": {"id", "run_id", "task_type", "attempt_number", "status"},
        "agent_turns": {
            "id",
            "invocation_id",
            "turn_index",
            "raw_response",
            "context_summary",
            "model_ms",
            "request_messages",
            "timing_notes",
        },
        "agent_tool_calls": {"id", "turn_id", "tool_name", "request_args", "status"},
    }
    with engine.begin() as connection:
        if _table_exists(connection, "model_interactions"):
            raise RuntimeError(
                "model_interactions 仍存在，请先执行 scripts/db/migrate_agent_audit.py "
                "删除旧审计表后启动服务"
            )
        for table_name, required in required_tables.items():
            if not _table_exists(connection, table_name):
                raise RuntimeError(
                    f"{table_name} 表不存在，请先执行 scripts/db/migrate_agent_audit.py "
                    "创建新审计表后启动服务"
                )
            actual = _get_table_columns(connection, table_name)
            missing = sorted(required - actual)
            if missing:
                raise RuntimeError(
                    f"{table_name} is missing agent audit contract columns: {missing}. "
                    "请先执行 scripts/db/migrate_agent_audit.py 重建审计表后启动服务"
                )
        if _table_exists(connection, "token_usage"):
            actual = _get_table_columns(connection, "token_usage")
            missing = sorted({"agent_turn_id", "reasoning_tokens"} - actual)
            if missing:
                raise RuntimeError(
                    "token_usage 仍是旧结构，缺少 agent_turn_id/reasoning_tokens: "
                    f"{missing}. 请先执行 scripts/db/migrate_agent_audit.py 重建 token_usage"
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


def init_db() -> None:
    """
    初始化数据库（创建所有表）

    说明: 使用 ORM 模型创建所有数据库表；目标数据库缺失时先自动创建

    注意：生产环境推荐使用 Alembic 迁移
    """
    from src.storage.models import Base

    ensure_database_exists()
    engine = get_engine()
    tables = [
        table
        for table in Base.metadata.sorted_tables
        if table.name != "paragraph_embeddings"
    ]
    Base.metadata.create_all(bind=engine, tables=tables)
    _create_graph_read_views(engine)
    _ensure_runtime_schema(engine)
    _assert_focus_contract_schema(engine)
    _assert_annotation_contract_schema(engine)
    _assert_agent_audit_contract_schema(engine)
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
