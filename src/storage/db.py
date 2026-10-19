"PostgreSQL 数据库引擎与 Session 管理，使用 SQLAlchemy"

from __future__ import annotations

import os
import re
from collections.abc import Generator
from contextlib import contextmanager, nullcontext
from typing import Any

from loguru import logger
from sqlalchemy import (
    CheckConstraint,
    Engine,
    ForeignKeyConstraint,
    UniqueConstraint,
    Uuid,
    create_engine,
    event,
    inspect,
    text,
)
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, QueuePool

from src.storage.database_url import resolve_database_url_from_env

_engine: Engine | None = None
_session_factory: sessionmaker | None = None


def get_database_url() -> str:
    "获取数据库连接 URL"
    return resolve_database_url_from_env("DATABASE")


def get_database_schema() -> str | None:
    "获取数据库 schema 名称"
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
    "用于从 SQLAlchemy URL 解析目标数据库名称"
    if not database_url.startswith("postgresql"):
        return None
    url = make_url(database_url)
    database = url.database
    if not database:
        return None
    return database


def _admin_database_url(database_url: str) -> str:
    "用于把目标库 URL 指向默认 postgres 库以执行建库 DDL"
    return make_url(database_url).set(database="postgres").render_as_string(hide_password=False)


def _safe_identifier(name: str) -> bool:
    "用于限制自动建库标识符为 PostgreSQL 安全格式"
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", name))


def ensure_database_exists() -> None:
    "用于首次启动时自动创建缺失的目标数据库"
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
    "获取 SQLAlchemy 引擎（单例模式）"
    global _engine

    if _engine is not None:
        return _engine

    database_url = get_database_url()

    pool_size = int(os.environ.get("DB_POOL_SIZE", "5"))
    max_overflow = int(os.environ.get("DB_MAX_OVERFLOW", "10"))
    pool_timeout = int(os.environ.get("DB_POOL_TIMEOUT", "30"))
    pool_recycle = int(os.environ.get("DB_POOL_RECYCLE", "1800"))
    connect_timeout = int(os.environ.get("DB_CONNECT_TIMEOUT", "5"))

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
        execution_options={"schema_translate_map": {None: database_schema}} if database_schema else {},
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
    "获取 Session 工厂（单例模式）"
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
    "获取 Session 上下文管理器，退出时自动 commit，异常回滚"
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
    "初始化数据库（创建所有表）"
    from src.storage.constraints import install_domain_constraints
    from src.storage.models import Base

    ensure_database_exists()
    engine = get_engine()
    validate_existing_schema(engine)
    # chapters/paragraphs 的 trgm 索引依赖 pg_trgm（gin_trgm_ops），paragraph_features
    # 的语义与词性向量列依赖 vector；两者都是 create_all 的硬前置，全新数据库缺任一
    # 扩展时 CREATE TABLE/INDEX 直接失败阻断启动
    dialect_name = getattr(getattr(engine, "dialect", None), "name", "")
    if dialect_name == "postgresql":
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)
    install_domain_constraints(engine)
    logger.info("Database tables created successfully")


def _column_type(column_type, dialect) -> str:
    "归一 PostgreSQL 双精度浮点类型的等价名称"
    result = str(column_type.compile(dialect=dialect)).lower()
    return "double precision" if result == "float" else result


def _schema_expression(engine, schema, table_name: str, expression: str) -> str:
    "通过只读执行计划取得 PostgreSQL 解析后的约束表达式"
    quote = engine.dialect.identifier_preparer.quote
    table = f"{quote(schema)}.{quote(table_name)}" if schema else quote(table_name)
    with engine.connect() if isinstance(engine, Engine) else nullcontext(engine) as connection:
        plan = connection.execute(
            text(f"EXPLAIN (VERBOSE, FORMAT JSON, COSTS FALSE) SELECT ({expression}) FROM {table}")
        ).scalar_one()
    return plan[0]["Plan"]["Output"][0]


def validate_existing_schema(engine, *, schema: str | None = None) -> None:
    "建表前只读核对已有表、字段与引用约束，拒绝不兼容结构"
    from src.storage.models import Base

    schema = schema or engine.get_execution_options().get("schema_translate_map", {}).get(None)
    inspector = inspect(engine)
    existing = set(inspector.get_table_names(schema=schema))
    problems = []
    expected = set(Base.metadata.tables)
    if existing and existing != expected:
        problems.append(
            f"业务表结构不匹配: missing={sorted(expected - existing)}, unexpected={sorted(existing - expected)}"
        )
    for table in Base.metadata.tables.values():
        initial_problem_count = len(problems)
        if table.name not in existing:
            continue
        primary = inspector.get_pk_constraint(table.name, schema=schema)["constrained_columns"]
        if primary != [column.name for column in table.primary_key]:
            problems.append(f"{table.name}: 主键不符合独立 UUIDv7 合同")
        columns = {column["name"]: column for column in inspector.get_columns(table.name, schema=schema)}
        extra = set(columns) - set(table.columns.keys())
        if extra:
            problems.append(f"{table.name}: 存在不属于当前结构的字段 {sorted(extra)}")
        for column in table.columns:
            if column.name not in columns:
                problems.append(f"{table.name}.{column.name}: 缺少字段")
            elif columns[column.name]["nullable"] != column.nullable:
                problems.append(f"{table.name}.{column.name}: 可空约束不匹配")
            elif isinstance(column.type, Uuid) or isinstance(getattr(column.type, "impl", None), Uuid):
                if not isinstance(columns[column.name]["type"], Uuid):
                    problems.append(f"{table.name}.{column.name}: 不是 UUID 类型")
            elif _column_type(column.type, engine.dialect) != _column_type(
                columns[column.name]["type"], engine.dialect
            ):
                problems.append(f"{table.name}.{column.name}: 字段类型不匹配")
        if len(problems) != initial_problem_count:
            continue

        def canonical(expression, table_name=table.name):
            return _schema_expression(engine, schema, table_name, str(expression)) if expression is not None else ""

        expected_unique = {
            (tuple(canonical(c.name) for c in constraint.columns), "")
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        expected_unique.update(
            (
                tuple(canonical(expression) for expression in index.expressions),
                canonical(index.dialect_options["postgresql"].get("where")),
            )
            for index in table.indexes
            if index.unique
        )
        actual_unique = {
            (tuple(canonical(c) for c in constraint["column_names"]), "")
            for constraint in inspector.get_unique_constraints(table.name, schema=schema)
        }
        actual_unique.update(
            (
                tuple(canonical(c) for c in index.get("expressions", index["column_names"])),
                canonical(index.get("dialect_options", {}).get("postgresql_where")),
            )
            for index in inspector.get_indexes(table.name, schema=schema)
            if index["unique"]
        )
        if expected_unique != actual_unique:
            problems.append(f"{table.name}: 唯一约束不匹配")
        expected_foreign = {
            (
                tuple(c.name for c in constraint.columns),
                tuple(element.column.table.name for element in constraint.elements),
                tuple(
                    element.column.table.schema or schema or inspector.default_schema_name
                    for element in constraint.elements
                ),
                tuple(element.column.name for element in constraint.elements),
                constraint.ondelete or "NO ACTION",
            )
            for constraint in table.constraints
            if isinstance(constraint, ForeignKeyConstraint)
        }
        actual_foreign = {
            (
                tuple(constraint["constrained_columns"]),
                tuple([constraint["referred_table"]] * len(constraint["referred_columns"])),
                tuple(
                    [constraint["referred_schema"] or schema or inspector.default_schema_name]
                    * len(constraint["referred_columns"])
                ),
                tuple(constraint["referred_columns"]),
                constraint.get("options", {}).get("ondelete", "NO ACTION"),
            )
            for constraint in inspector.get_foreign_keys(table.name, schema=schema, postgresql_ignore_search_path=True)
        }
        if expected_foreign != actual_foreign:
            problems.append(f"{table.name}: 外键约束不匹配")
        expected_checks = {
            constraint.name: canonical(constraint.sqltext)
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        actual_checks = {
            constraint["name"]: canonical(constraint["sqltext"])
            for constraint in inspector.get_check_constraints(table.name, schema=schema)
        }
        if expected_checks != actual_checks:
            problems.append(f"{table.name}: 检查约束不匹配")
    if problems:
        raise RuntimeError("Storage 结构不兼容，请在全新结构中从原始输入重建；" + "；".join(problems))


def dispose_engine() -> None:
    "释放数据库引擎资源"
    global _engine, _session_factory

    if _engine is not None:
        _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("SQLAlchemy engine disposed")


def get_pool_status() -> dict | None:
    "获取连接池状态"
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
