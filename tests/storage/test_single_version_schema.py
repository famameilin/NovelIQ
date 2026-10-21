"""初始化拒绝旧结构，全部测试使用独立测试 schema"""

from contextlib import contextmanager
from uuid import uuid4

import pytest
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
        db.validate_existing_schema(engine)
        from scripts.db.init_schema import inspect_current_schema

        assert inspect_current_schema(engine, schema=schema)["ready"] is True


def test_old_stage_structure_refused_before_creating_tables_or_changing_data(monkeypatch):
    with isolated_schema(monkeypatch) as (engine, schema):
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE event_revisions (id uuid PRIMARY KEY, summary text NOT NULL)"))
            connection.execute(text("INSERT INTO event_revisions VALUES (:id, '旧记录保留')"), {"id": str(uuid4())})
        with pytest.raises(RuntimeError, match="结构不兼容"):
            db.init_db()
        assert inspect(engine).get_table_names(schema=schema) == ["event_revisions"]
        with engine.connect() as connection:
            assert connection.execute(text("SELECT summary FROM event_revisions")).scalar_one() == "旧记录保留"


@pytest.mark.parametrize(
    "alter",
    [
        "ALTER TABLE event_records ADD COLUMN current_revision_id uuid",
        "ALTER TABLE event_records ALTER COLUMN summary DROP NOT NULL",
        "ALTER TABLE event_records ALTER COLUMN summary TYPE integer USING NULL",
        "ALTER TABLE event_records DROP CONSTRAINT uq_complete_events_producer_local_key",
        "ALTER TABLE event_records DROP CONSTRAINT complete_events_producer_fkey",
        "ALTER TABLE event_records DROP CONSTRAINT ck_events_payoff",
    ],
)
def test_mixed_fields_and_missing_constraints_are_refused_without_repair(monkeypatch, alter):
    with isolated_schema(monkeypatch) as (engine, schema):
        db.init_db()
        with engine.begin() as connection:
            connection.execute(text(alter))
        before = inspect(engine).get_table_names(schema=schema)
        with pytest.raises(RuntimeError, match="结构不兼容"):
            db.init_db()
        assert inspect(engine).get_table_names(schema=schema) == before


def test_foreign_key_to_same_table_in_another_schema_is_refused(monkeypatch):
    with isolated_schema(monkeypatch) as (engine, schema):
        db.init_db()
        other_schema = schema + "_history"
        try:
            with engine.begin() as connection:
                connection.execute(text(f'CREATE SCHEMA "{other_schema}"'))
                connection.execute(text(f'CREATE TABLE "{other_schema}".runs (id uuid PRIMARY KEY)'))
                connection.execute(text(f'ALTER TABLE "{schema}".chapters DROP CONSTRAINT chapters_run_fkey'))
                connection.execute(
                    text(
                        f'ALTER TABLE "{schema}".chapters ADD FOREIGN KEY (run_id) '
                        f'REFERENCES "{other_schema}".runs(id) ON DELETE CASCADE'
                    )
                )
            with pytest.raises(RuntimeError, match="chapters: 外键约束不匹配"):
                db.init_db()
            from scripts.db.init_schema import inspect_current_schema

            assert inspect_current_schema(engine, schema=schema)["ready"] is False
        finally:
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{other_schema}" CASCADE'))
