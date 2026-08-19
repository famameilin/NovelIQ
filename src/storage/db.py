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
    # 2026-08-14 D9：默认 120s（原 30s 会误杀 HNSW 建索引与十万级段落批量插入）；
    # 仍可经 DB_STATEMENT_TIMEOUT 覆盖
    statement_timeout = int(os.environ.get("DB_STATEMENT_TIMEOUT", "120000"))
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
    def on_checkin(dbapi_conn, connection_record):
        if _engine is not None:
            logger.debug(f"Pool checkin: active={_engine.pool.status()}")

    # 2026-08-13 P2：启动期合同校验——引擎创建后立即验证连接可达与数据库版本，
    # 避免 URL/schema/服务未起等配置错误延迟到首次查询才暴露（pool_pre_ping 只处理
    # 失效连接，不验证首次连接）；连接失败按原始异常抛出，由调用方决定启动策略
    with _engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        server_version_num = conn.execute(text("SHOW server_version_num")).scalar_one()
    logger.info(f"Database connection verified (server_version_num={server_version_num})")

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


def _assert_focus_contract_schema(engine: Engine) -> None:
    """
    修改时间: 2026-04-30
    任务: diagnosis-latest-only-reference-contract
    修改原因: latest-only 之后只校验真实焦点合同列，不再把 reference_contract_version 当成启动前置条件。

    说明: 启动时显式检查 `cloud_analysis` 是否具备完整焦点合同列；
    缺失即阻断启动（当前只有最新口径，不再检查旧结构残留）
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
            "chapter_id",
            "candidate_key",
            "content",
            "start",
            "end",
            "speaker",
            "tone",
            "is_inner_monologue",
            "confidence",
            "event_id",
        },
        "case_pool_cases": {
            "id",
            "run_id",
            "type",
            "chapter_id",
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
            "target_setup_event_id",
            "target_payoff_event_id",
        },
        "event_nodes": {
            "event_id",
            "event_revision",
            "run_id",
            "chapter_id",
            "chapter_order",
            "anchor_paragraph_ids",
            "char_start",
            "char_end",
            "text_hash",
            "evidence",
            "graph_version_id",
            "tree_id",
            "cause_role",
        },
        "event_edges": {
            "edge_id",
            "run_id",
            "edge_type",
            "source_event_id",
            "target_event_id",
            "source_chapter_id",
            "target_chapter_id",
            "evidence",
        },
        "graph_facts": {
            "event_id",
            "event_revision",
            "evidence",
        },
        "foreshadowing_threads": {
            "setup_event_id",
            "payoff_event_id",
        },
    }
    with engine.begin() as connection:
        required_tables = {"event_nodes", "event_edges"}
        for table_name, required in required_columns.items():
            if not _table_exists(connection, table_name):
                if table_name in required_tables:
                    raise RuntimeError(
                        f"{table_name} 表不存在，请先按当前事件合同重建数据库后启动服务"
                    )
                continue
            actual = _get_table_columns(connection, table_name)
            missing = sorted(required - actual)
            if missing:
                raise RuntimeError(
                    f"{table_name} is missing annotation contract columns: {missing}. "
                    "Please recreate or explicitly migrate the continuity tables before starting the service."
                )


def _assert_agent_audit_contract_schema(engine: Engine) -> None:
    """
    2026-08-10 用于校验 Agent 审计三表与 token_usage 新结构就绪

    说明: 当前只有最新口径（create_all 直接建出新库），
    启动时校验审计表与 token_usage 合同列齐备；缺失即阻断启动。
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
        for table_name, required in required_tables.items():
            if not _table_exists(connection, table_name):
                raise RuntimeError(f"{table_name} 表不存在，请先执行 init_db 建表后启动服务")
            actual = _get_table_columns(connection, table_name)
            missing = sorted(required - actual)
            if missing:
                raise RuntimeError(
                    f"{table_name} is missing agent audit contract columns: {missing}. "
                    "请先执行 init_db 重建审计表后启动服务"
                )
        if _table_exists(connection, "token_usage"):
            actual = _get_table_columns(connection, "token_usage")
            missing = sorted({"agent_turn_id", "reasoning_tokens"} - actual)
            if missing:
                raise RuntimeError(
                    "token_usage 仍是旧结构，缺少 agent_turn_id/reasoning_tokens: "
                    f"{missing}. 请先执行 init_db 重建 token_usage"
                )


def _assert_paragraph_contract_schema(engine: Engine) -> None:
    """2026-08-14 用于校验 paragraphs 段落事实源表合同列齐备"""
    dialect_name = getattr(getattr(engine, "dialect", None), "name", "")
    if dialect_name != "postgresql":
        return

    required_columns = {
        "run_id",
        "paragraph_id",
        "chapter_id",
        "paragraph_index",
        "source_paragraph_index",
        "fragment_index",
        "local_start_char",
        "local_end_char",
        "global_start_char",
        "global_end_char",
        "char_count",
        "token_count",
        "text",
        "content_hash",
        "splitter_version",
        "tokenizer_version",
        "created_at",
    }
    with engine.begin() as connection:
        if not _table_exists(connection, "paragraphs"):
            return
        actual = _get_table_columns(connection, "paragraphs")
        missing = sorted(required_columns - actual)
        if missing:
            raise RuntimeError(
                "paragraphs is missing paragraph contract columns: "
                f"{missing}. Please recreate or explicitly migrate the paragraphs table "
                "so that it includes the full paragraph contract column set before starting the service."
            )


def _assert_paragraph_metrics_contract_schema(engine: Engine) -> None:
    """
    2026-08-14 用于校验段落指标/主题派生表合同列齐备

    缺失即阻断启动；表不存在时跳过（旧库未升级前不强制建表）
    """
    dialect_name = getattr(getattr(engine, "dialect", None), "name", "")
    if dialect_name != "postgresql":
        return

    required_tables = {
        "paragraph_metrics": {
            "run_id",
            "paragraph_id",
            "metric_version",
            "token_count",
            "char_count",
            "sentence_count",
            "sentence_char_sum",
            "sentence_char_sum_sq",
            "positive_weight_sum",
            "negative_weight_sum",
            "fight_weight_sum",
            "exclaim_count",
            "question_count",
            "pause_count",
            "dialogue_char_count",
            "sensory_hit_count",
            "imagery_hit_count",
            "metaphor_sentence_count",
            "function_word_counts",
            "semantic_category_counts",
            "surface_tension_z",
            "surface_tension",
            "created_at",
        },
        "paragraph_topics": {
            "id",
            "run_id",
            "paragraph_id",
            "topic_id",
            "topic_weight",
            "inference_token_count",
            "topic_model_version",
        },
        "paragraph_curves": {
            "run_id",
            "paragraph_id",
            "curve_version",
            "pos_density",
            "neg_density",
            "net_density",
            "smoothed_net_density",
            "surface_tension",
            "smoothed_surface_tension",
            "created_at",
        },
    }
    with engine.begin() as connection:
        for table_name, required in required_tables.items():
            if not _table_exists(connection, table_name):
                continue
            actual = _get_table_columns(connection, table_name)
            missing = sorted(required - actual)
            if missing:
                raise RuntimeError(
                    f"{table_name} is missing paragraph contract columns: {missing}. "
                    "Please recreate or explicitly migrate the table before starting the service."
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
    # 2026-08-14 P1：chapters 的 idx_chapters_run_text_trgm 依赖 pg_trgm 扩展（gin_trgm_ops），
    # 全新数据库必须先建扩展再 create_all，否则 CREATE INDEX 直接失败阻断启动；
    # 与 vector 扩展（vector_schema.ensure_paragraph_embeddings_schema）同口径按需创建
    dialect_name = getattr(getattr(engine, "dialect", None), "name", "")
    if dialect_name == "postgresql":
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    tables = [
        table
        for table in Base.metadata.sorted_tables
        if table.name != "paragraph_embeddings"
    ]
    Base.metadata.create_all(bind=engine, tables=tables)
    _assert_focus_contract_schema(engine)
    _assert_annotation_contract_schema(engine)
    _assert_agent_audit_contract_schema(engine)
    _assert_paragraph_contract_schema(engine)
    _assert_paragraph_metrics_contract_schema(engine)
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
