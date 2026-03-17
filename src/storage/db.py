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
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from loguru import logger


_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker] = None


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
    pool_recycle = int(os.environ.get("DB_POOL_RECYCLE", "3600"))
    echo = os.environ.get("DB_ECHO", "false").lower() == "true"

    _engine = create_engine(
        database_url,
        poolclass=QueuePool,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
        pool_pre_ping=True,
        echo=echo,
    )

    if database_url.startswith("postgresql"):

        @event.listens_for(_engine, "connect")
        def set_postgresql_settings(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("SET TIME ZONE 'UTC'")
            cursor.close()

    logger.info(f"Created SQLAlchemy engine for {database_url.split(':')[0]} (pool_size={pool_size})")

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


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    获取 Session 的上下文管理器

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 提供上下文管理器方式获取 Session，自动处理提交和回滚

    Yields:
        SQLAlchemy Session 实例

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

    创建时间: 2026-03-15
    创建者: TraeAI
    任务: postgresql-migration
    说明: 使用 ORM 模型创建所有数据库表

    注意：生产环境推荐使用 Alembic 迁移
    """
    from src.storage.models import Base

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
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
