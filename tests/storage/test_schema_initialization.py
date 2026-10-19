"""当前 schema 检查保持只读，初始化不恢复已废弃的模型"""

from __future__ import annotations

from sqlalchemy import inspect, text

from scripts.db.init_schema import inspect_current_schema
from src.storage.db import get_database_schema, get_engine, init_db


def test_current_schema_is_ready_for_current_orm(db_session) -> None:
    schema = get_database_schema()
    assert schema is not None
    result = inspect_current_schema(get_engine(), schema=schema)
    assert result == {"ready": True, "missing_tables": [], "missing_columns": {}}


def test_read_only_inspection_does_not_create_missing_schema(db_session) -> None:
    engine = get_engine()
    missing_schema = "not_initialized_schema"
    assert not inspect(engine).has_schema(missing_schema)
    result = inspect_current_schema(engine, schema=missing_schema)
    assert result["ready"] is False and "runs" in result["missing_tables"]
    assert not inspect(engine).has_schema(missing_schema)


def test_initialization_is_idempotent_for_current_schema(db_session) -> None:
    schema = get_database_schema()
    assert schema is not None
    engine = get_engine()
    before = inspect_current_schema(engine, schema=schema)
    init_db()
    assert inspect_current_schema(engine, schema=schema) == before


def test_schema_inspection_detects_missing_column(db_session) -> None:
    schema = get_database_schema()
    assert schema is not None
    engine = get_engine()
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'ALTER TABLE "{schema}".chapters DROP COLUMN title'))
            result = inspect_current_schema(connection, schema=schema)
            assert result["ready"] is False
            assert "title" in result["missing_columns"]["chapters"]
        finally:
            # 测试库 DDL 也回滚，避免下一项用例继承缺失的列
            transaction.rollback()
    assert inspect_current_schema(engine, schema=schema)["ready"] is True
