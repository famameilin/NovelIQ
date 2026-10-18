"""UUIDv7 运行与独立 task 短 ID 的精确映射合同"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from src.storage.id_mapping import (
    TaskIDNotFoundError,
    convert_response_run_ids_to_task_ids,
    generate_run_id,
    generate_task_id,
    run_id_to_task_id,
    task_id_to_run_id,
)


@pytest.fixture
def mapped_storage(monkeypatch):
    run_id = generate_run_id()
    task_id = generate_task_id()
    runs = Mock()
    runs.get_run.side_effect = lambda identifier: (
        {"run_id": run_id, "task_id": task_id} if identifier == run_id else None
    )
    runs.get_run_by_task_id.side_effect = lambda identifier: (
        {"run_id": run_id, "task_id": task_id} if identifier == task_id else None
    )
    storage = SimpleNamespace(runs=runs)
    monkeypatch.setattr("src.storage.service.get_storage", lambda: storage)
    return storage, run_id, task_id


def test_run_generator_uses_uuid7_and_unique_values():
    identifiers = [generate_run_id() for _ in range(100)]
    assert len(set(identifiers)) == 100
    assert all(len(value) == 36 and UUID(value).version == 7 for value in identifiers)
    assert identifiers == sorted(identifiers)


def test_task_generator_uses_independent_short_hex_values():
    identifiers = [generate_task_id() for _ in range(100)]
    assert len(set(identifiers)) == 100
    assert all(len(value) == 8 and set(value) <= set("0123456789abcdef") for value in identifiers)


def test_run_mapping_reads_saved_task_instead_of_uuid_prefix(mapped_storage):
    storage, run_id, task_id = mapped_storage
    assert run_id_to_task_id(run_id, storage) == task_id
    storage.runs.get_run.assert_called_once_with(run_id)


def test_task_mapping_uses_exact_saved_identity(mapped_storage):
    storage, run_id, task_id = mapped_storage
    assert task_id_to_run_id(task_id, storage) == run_id
    storage.runs.get_run_by_task_id.assert_called_once_with(task_id)


@pytest.mark.parametrize("identifier", ["", None, "1234567", "123456789"])
def test_task_length_is_validated_before_reading_storage(identifier, mapped_storage):
    storage, _, _ = mapped_storage
    with pytest.raises(ValueError, match="Invalid task_id"):
        task_id_to_run_id(identifier, storage)
    storage.runs.get_run_by_task_id.assert_not_called()


def test_missing_run_mapping_is_explicit(mapped_storage):
    storage, _, _ = mapped_storage
    with pytest.raises(TaskIDNotFoundError, match="No task_id found"):
        run_id_to_task_id(generate_run_id(), storage)


def test_like_wildcards_cannot_select_a_similar_run(mapped_storage):
    storage, _, _ = mapped_storage
    with pytest.raises(TaskIDNotFoundError):
        task_id_to_run_id("%_______", storage)
    storage.runs.get_run_by_task_id.assert_called_once_with("%_______")


def test_default_mapping_uses_the_injected_storage(mapped_storage):
    _, run_id, task_id = mapped_storage
    assert run_id_to_task_id(run_id) == task_id
    assert task_id_to_run_id(task_id) == run_id


def test_response_conversion_uses_saved_mapping_and_preserves_source(mapped_storage):
    _, run_id, task_id = mapped_storage
    source = {"run_id": run_id, "name": "test", "nested": [{"run_id": run_id}, {"run_id": "short-id"}]}
    result = convert_response_run_ids_to_task_ids(source)
    assert result == {"task_id": task_id, "name": "test", "nested": [{"task_id": task_id}, {"run_id": "short-id"}]}
    assert source["run_id"] == run_id
    assert "run_id" in source["nested"][0]


@pytest.mark.parametrize("source", [{}, [], None, 1, "unchanged"])
def test_response_conversion_preserves_values_without_run_identity(source):
    assert convert_response_run_ids_to_task_ids(source) == source
