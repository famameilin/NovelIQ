"""公开数据边界与包内事务所有权，不使用项目数据库"""

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from sqlalchemy import Uuid, create_engine, inspect, literal, select
from sqlalchemy.orm import Session

from src.storage import Storage, StorageWriteError, new_id
from src.storage.detached import detached
from src.storage.models import Base, GraphFact
from src.storage.operations import OperationRunner
from src.storage.records.models import GraphFactRecord


def test_every_table_has_one_uuid_primary_key():
    assert len(Base.metadata.tables) == 35
    for table in Base.metadata.tables.values():
        keys = list(table.primary_key.columns)
        assert len(keys) == 1, table.name
        assert isinstance(keys[0].type.impl, Uuid), table.name
        assert keys[0].default is not None, table.name


def test_storage_does_not_export_transaction_or_query_controls():
    storage = Storage()
    for name in ("transaction", "read", "commit", "rollback", "savepoint", "execute", "session", "connection"):
        assert not hasattr(storage, name)


def test_nested_orm_is_replaced_and_mutable_values_are_isolated():
    @dataclass
    class Envelope:
        content: object

    fact = GraphFact(graph_fact_id=new_id(), reason="original")
    source = Envelope({"items": [SimpleNamespace(fact=fact)], "labels": ["original"]})
    result = detached(source)
    assert isinstance(result.content["items"][0].fact, GraphFactRecord)
    assert inspect(result.content["items"][0].fact, raiseerr=False) is None
    source.content["labels"].append("changed")
    fact.reason = "changed"
    assert result.content["labels"] == ["original"]
    assert result.content["items"][0].fact.reason == "original"


def test_rows_are_named_and_remain_usable_after_connection_closes():
    engine = create_engine("sqlite://")
    try:
        with engine.connect() as connection:
            result = detached(connection.execute(select(literal(7).label("answer"))))
        assert result[0].answer == 7
        with pytest.raises(TypeError):
            result[0][0]
    finally:
        engine.dispose()


def test_resources_and_sql_expressions_are_rejected():
    session = Session()
    try:
        for value in (session, select(1), {"hidden": session}):
            with pytest.raises(TypeError):
                detached(value)
    finally:
        session.close()


class _Connection:
    def __init__(self, *, commit_error=None, rollback_error=None):
        self.events = []
        self.commit_error = commit_error
        self.rollback_error = rollback_error

    def flush(self):
        self.events.append("flush")

    def commit(self):
        self.events.append("commit")
        if self.commit_error:
            raise self.commit_error

    def rollback(self):
        self.events.append("rollback")
        if self.rollback_error:
            raise self.rollback_error

    def close(self):
        self.events.append("close")


def test_complete_write_is_committed_before_returning():
    connection = _Connection()
    runner = OperationRunner(lambda: connection)
    assert runner.run(lambda session: {"saved": True}) == {"saved": True}
    assert connection.events == ["flush", "commit", "close"]


def test_lost_commit_receipt_preserves_transport_and_rollback_classification():
    connection = _Connection(commit_error=OSError("receipt lost"))
    with pytest.raises(StorageWriteError) as failure:
        OperationRunner(lambda: connection).run(lambda session: None)
    assert failure.value.transport_error
    assert not failure.value.rollback_failed
    assert connection.events == ["flush", "commit", "rollback", "close"]


def test_rollback_failure_is_not_misreported_as_unsaved():
    connection = _Connection(commit_error=OSError("receipt lost"), rollback_error=RuntimeError("disconnected"))
    with pytest.raises(StorageWriteError) as failure:
        OperationRunner(lambda: connection).run(lambda session: None)
    assert failure.value.rollback_failed
    assert connection.events[-1] == "close"


def test_diagnosis_formal_entry_allocates_uuid7_session(monkeypatch):
    import asyncio
    from uuid import UUID

    from src.agents.diagnosis import runner

    received = {}
    sentinel = object()

    async def capture(**kwargs):
        received.update(kwargs)
        return sentinel

    monkeypatch.setattr(runner, "_run_diagnosis_agent", capture)
    storage = Storage()
    assert (
        asyncio.run(
            runner.run_diagnosis_agent(session=storage, run_id=new_id(), novel_id=new_id(), audit_recorder=object())
        )
        is sentinel
    )
    assert received["session"] is storage
    assert UUID(received["execution_id"]).version == 7
