"""
消歧评测指标测试

创建时间: 2026-04-02
创建者: TraeAI
任务: P2.2-entity-type-metrics
说明: 测试 compute_metrics_by_entity_type 函数
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.eval.disambig_metrics import (
    compute_metrics_by_entity_type,
    compute_run_metrics,
)


class _DummyGraphRepo:
    def __init__(self, entities=None, alias_map=None):
        self._entities = entities or []
        self._alias_map = alias_map or {}

    def fetch_entities(self, run_id, entity_type=None, status=None):
        return self._entities

    def fetch_alias_map(self, run_id):
        return self._alias_map


def _make_entity(canonical_name, entity_type="character"):
    entity = MagicMock()
    entity.canonical_name = canonical_name
    entity.entity_type = entity_type
    return entity


def test_compute_metrics_by_entity_type_groups_by_type():
    gold_records = [
        {"alias": "伯安", "canonical": "贺重明", "judgment": "should_merge"},
        {"alias": "赤甲卫", "canonical": "赤甲卫", "judgment": "should_not_merge"},
    ]
    system_merges = [
        {"alias": "伯安", "canonical": "贺重明"},
        {"alias": "赤甲卫", "canonical": "赤甲卫"},
    ]

    session = MagicMock()
    mock_graph_repo = _DummyGraphRepo(
        entities=[
            _make_entity("伯安", "character"),
            _make_entity("贺重明", "character"),
            _make_entity("赤甲卫", "group"),
        ],
        alias_map={"赤甲卫": "赤甲卫"},
    )

    with pytest.MonkeyPatch().context() as m:
        m.setattr(
            "src.storage.repositories.GraphRepository",
            lambda session: mock_graph_repo,
        )
        result = compute_metrics_by_entity_type(
            gold_records, system_merges, "run-1", session
        )

    assert "character" in result
    assert "group" in result


def test_compute_metrics_by_entity_type_missing_type_warning(caplog):
    import logging
    from loguru import logger

    class PropagateHandler(logging.Handler):
        def emit(self, record):
            logging.getLogger(record.name).handle(record)

    handler_id = logger.add(PropagateHandler(), format="{message}")

    gold_records = [
        {"alias": "灵禽", "canonical": "赤羽炽尾鸡", "judgment": "should_not_merge"},
    ]
    system_merges = [{"alias": "灵禽", "canonical": "灵禽"}]

    session = MagicMock()
    mock_graph_repo = _DummyGraphRepo(
        entities=[_make_entity("赤羽炽尾鸡", "creature")],
        alias_map={"赤羽炽尾鸡": "赤羽炽尾鸡"},
    )

    with pytest.MonkeyPatch().context() as m:
            m.setattr(
                "src.storage.repositories.GraphRepository",
                lambda session: mock_graph_repo,
            )
            type_metrics = compute_metrics_by_entity_type(
                gold_records, system_merges, "run-1", session
            )

    logger.remove(handler_id)
    assert "灵禽" in caplog.text
    assert "character" in type_metrics


def test_compute_run_metrics_correct_merge():
    gold_records = [
        {"alias": "猴子", "canonical": "侯飞白", "judgment": "should_merge"},
    ]
    system_merges = [
        {"alias": "猴子", "canonical": "侯飞白"},
    ]

    metrics, details = compute_run_metrics(gold_records, system_merges, "run-1")

    assert metrics.correct_merges == 1
    assert metrics.wrong_merges == 0
    assert metrics.missed_merges == 0


def test_compute_run_metrics_false_merge():
    gold_records = [
        {"alias": "灵禽", "canonical": "赤羽炽尾鸡", "judgment": "should_not_merge"},
    ]
    system_merges = [
        {"alias": "灵禽", "canonical": "赤羽炽尾鸡"},
    ]

    metrics, details = compute_run_metrics(gold_records, system_merges, "run-1")

    assert metrics.correct_merges == 0
    assert metrics.wrong_merges == 1
    assert metrics.false_merge_rate == 1.0


def test_compute_run_metrics_missed_merge():
    gold_records = [
        {"alias": "猴子", "canonical": "侯飞白", "judgment": "should_merge"},
    ]
    system_merges = []

    metrics, details = compute_run_metrics(gold_records, system_merges, "run-1")

    assert metrics.missed_merges == 1
    assert metrics.gold_should_merge_total == 1
