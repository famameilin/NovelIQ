"""
创建时间: 2026-03-15
创建者: TraeAI
任务: postgresql-migration
说明: PostgreSQL 数据库引擎与 Session 管理，使用 SQLAlchemy

本模块提供：
- get_engine(): 获取 SQLAlchemy 引擎（单例）
- SessionLocal: Session 工厂类
- get_session(): 上下文管理器，用于获取 Session
- init_db(): 初始化数据库（创建所有表）

修改时间: 2026-04-04
修改者: AI Assistant
任务: fix-backend-stability
修改内容: 添加数据库连接超时和 SQL 执行超时配置，添加连接池监控事件
"""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager

from loguru import logger
from sqlalchemy import Engine, create_engine, event, text
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


def get_engine():
    """
    获取 SQLAlchemy 引擎（单例模式）

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
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

    connect_args = {
        "connect_timeout": connect_timeout,
        "options": f"-c statement_timeout={statement_timeout}",
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

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
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


def _ensure_runtime_schema(engine: Engine) -> None:
    """
    为历史 PostgreSQL 表补齐运行时需要的非破坏性 schema。

    创建时间: 2026-04-22
    创建者: Codex
    任务: distinguish-thinking-visibility
    说明: 当前项目仍以 create_all 为主，旧库不会自动跟随 ORM 演进。
          这里仅做“补列 / 补索引”这类非破坏性修复，不在应用启动时静默删除列或重建约束。
    """
    dialect_name = getattr(getattr(engine, "dialect", None), "name", "")
    if dialect_name != "postgresql":
        return

    statements = [
        "ALTER TABLE model_interactions ADD COLUMN IF NOT EXISTS reasoning_tokens INTEGER",
        "ALTER TABLE model_interactions ADD COLUMN IF NOT EXISTS thinking_state VARCHAR(20) NOT NULL DEFAULT 'unknown'",
        "CREATE INDEX IF NOT EXISTS idx_chunk_curves_run_id ON chunk_curves (run_id)",
        "CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_run_id ON chunk_embeddings (run_id)",
    ]

    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    获取 Session 的上下文管理器

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 提供上下文管理器方式获取 Session，自动处理提交和回滚

    修改时间: 2026-04-04
    修改者: AI Assistant
    任务: fix-backend-stability
    修改内容: 添加只读场景行为说明

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

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 使用 ORM 模型创建所有数据库表

    注意：生产环境推荐使用 Alembic 迁移
    """
    from src.storage.models import Base

    engine = get_engine()
    tables = list(Base.metadata.sorted_tables)
    if not include_level3_tables:
        tables = [table for table in tables if table.name != "chunk_embeddings"]
    Base.metadata.create_all(bind=engine, tables=tables)
    _ensure_runtime_schema(engine)
    logger.info("Database tables created successfully")


def dispose_engine() -> None:
    """
    释放数据库引擎资源

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
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

    创建时间: 2026-04-04
    创建者: AI Assistant
    任务: fix-backend-stability
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
