"""首次启动自动建库单元测试"""

from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy.sql.elements import TextClause

from src.storage.db import (
    _admin_database_url,
    _database_name_from_url,
    _safe_identifier,
    ensure_database_exists,
)


def test_database_name_parsed_from_plain_url() -> None:
    """2026-08-08 用于验证普通 URL 能解析出目标库名"""
    url = "postgresql+psycopg://user:pass@localhost:5432/novel_analysis"
    assert _database_name_from_url(url) == "novel_analysis"


def test_database_name_parsed_with_query_params() -> None:
    """2026-08-08 用于验证带查询参数的 URL 仍能解析库名"""
    url = "postgresql+psycopg://user:pass@localhost:5432/novel_analysis?options=-c%20search_path%3Dtest"
    assert _database_name_from_url(url) == "novel_analysis"


def test_database_name_none_for_non_postgres() -> None:
    """2026-08-08 用于验证非 PostgreSQL 方言不触发建库"""
    assert _database_name_from_url("sqlite:///tmp.db") is None


def test_admin_url_points_to_postgres_database() -> None:
    """2026-08-08 用于验证管理连接固定指向 postgres 默认库"""
    url = "postgresql+psycopg://user:pass@localhost:5432/novel_analysis"
    admin = _admin_database_url(url)
    assert admin == "postgresql+psycopg://user:pass@localhost:5432/postgres"


def test_safe_identifier_guards_sql_injection() -> None:
    """2026-08-08 用于验证非法库名不会进入建库 DDL"""
    assert _safe_identifier("novel_analysis") is True
    assert _safe_identifier('novel"; DROP DATABASE x; --') is False
    assert _safe_identifier("novel-analysis") is False


def _set_database_environment(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost:5432/novel_analysis")
    monkeypatch.setenv("DATABASE_USERNAME", "u")
    monkeypatch.setenv("DATABASE_PASSWORD", "p")


def test_ensure_database_exists_skips_when_already_present(monkeypatch) -> None:
    """2026-08-08 用于验证目标库已存在时不执行 CREATE DATABASE"""
    executed: list[str] = []
    connection = MagicMock()
    connection.execute.side_effect = lambda stmt, *args, **kwargs: _record_and_return_truthy(executed, stmt)
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    monkeypatch.setattr("src.storage.db.create_engine", lambda *a, **k: engine)
    _set_database_environment(monkeypatch)

    ensure_database_exists()

    assert executed == ["SELECT 1 FROM pg_database WHERE datname = :name"]
    connection.execute.assert_called_once()


def test_ensure_database_exists_creates_missing_database(monkeypatch) -> None:
    """2026-08-08 用于验证缺失数据库时执行一次 CREATE DATABASE"""
    executed: list[str] = []
    connection = MagicMock()
    connection.execute.side_effect = lambda stmt, *args, **kwargs: _record_and_return_falsy(executed, stmt)
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    monkeypatch.setattr("src.storage.db.create_engine", lambda *a, **k: engine)
    _set_database_environment(monkeypatch)

    ensure_database_exists()

    assert 'CREATE DATABASE "novel_analysis"' in executed
    assert executed[0] == "SELECT 1 FROM pg_database WHERE datname = :name"


def test_ensure_database_exists_respects_disable_switch(monkeypatch) -> None:
    """2026-08-08 用于验证 DB_AUTO_CREATE_DATABASE=false 时完全不连接"""
    created: list[bool] = []

    def fail(*args, **kwargs):
        created.append(True)
        raise AssertionError("create_engine 不应被调用")

    monkeypatch.setattr("src.storage.db.create_engine", fail)
    monkeypatch.setenv("DB_AUTO_CREATE_DATABASE", "false")
    _set_database_environment(monkeypatch)

    ensure_database_exists()

    assert created == []


def _record_and_return_truthy(executed: list[str], stmt) -> MagicMock:
    """2026-08-08 用于记录探测 SQL 并模拟库已存在"""
    executed.append(_sql_text(stmt))
    result = MagicMock()
    result.scalar_one_or_none.return_value = 1
    return result


def _record_and_return_falsy(executed: list[str], stmt) -> MagicMock:
    """2026-08-08 用于记录 SQL 并模拟库不存在"""
    executed.append(_sql_text(stmt))
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    return result


def _sql_text(stmt) -> str:
    """2026-08-08 用于提取可比较的 SQL 文本"""
    return stmt.text if isinstance(stmt, TextClause) else str(stmt)
