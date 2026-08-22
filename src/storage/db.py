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
from sqlalchemy import Engine, create_engine, event, text
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
    return make_url(database_url).set(database="postgres").render_as_string(hide_password=False)


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
        def set_postgresql_settings(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("SET TIME ZONE 'UTC'")
            if database_schema:
                # 连接池里的连接被复用时，仍要确保 search_path 固定在当前运行时 schema，
                # 避免测试并发时把 ORM/原生 SQL 混写回 public 或其他进程的隔离空间
                cursor.execute(f"SET search_path TO {database_schema}, public")
            cursor.close()

    @event.listens_for(_engine, "checkout")
    def on_checkout(_dbapi_conn, _conn_record, _conn_proxy):
        if _engine is not None:
            logger.debug(f"Pool checkout: active={_engine.pool.status()}")

    @event.listens_for(_engine, "checkin")
    def on_checkin(_dbapi_conn, _connection_record):
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


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """获取 Session 上下文管理器，退出时自动 commit，异常回滚。"""
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
    tables = [table for table in Base.metadata.sorted_tables if table.name != "paragraph_embeddings"]
    Base.metadata.create_all(bind=engine, tables=tables)
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
