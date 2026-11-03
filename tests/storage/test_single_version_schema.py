"""空 schema 按当前 ORM 初始化，全部测试使用独立测试 schema"""

from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy import inspect, text

from src.storage import db
from src.storage.models import Base
from tests.conftest import _build_test_engine, get_test_database_url


@contextmanager
def isolated_schema(monkeypatch):
    schema = "test_version_" + uuid4().hex
    engine = _build_test_engine(get_test_database_url(), schema)
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    monkeypatch.setattr(db, "ensure_database_exists", lambda: None)
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    try:
        yield engine, schema
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def test_empty_schema_initializes_exactly_30_single_uuid_tables(monkeypatch):
    with isolated_schema(monkeypatch) as (engine, schema):
        db.init_db()
        inspector = inspect(engine)
        assert set(inspector.get_table_names(schema=schema)) == set(Base.metadata.tables)
        assert len(Base.metadata.tables) == 30
        for table in Base.metadata.tables.values():
            assert len(table.primary_key.columns) == 1
            assert str(next(iter(table.primary_key.columns)).type.compile(dialect=engine.dialect)) == "UUID"
        from scripts.db.init_schema import inspect_current_schema

        assert inspect_current_schema(engine, schema=schema)["ready"] is True


