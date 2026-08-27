from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.storage.repositories.stats import metrics


def test_fetch_token_usage_stats_marks_partial_when_annotation_chain_is_missing() -> None:
    """
    2026-08-10 用于验证新审计表中存在 annotation 成功回合但 token_usage 没有对应桶时
    summary 标记为 partial 并暴露 coverage_gaps。
    """
    session = MagicMock()
    with (
        patch.object(
            metrics,
            "_fetch_usage_summary",
            return_value={
                "call_count": 2,
                "total_prompt_tokens": 100,
                "total_completion_tokens": 20,
                "total_tokens": 120,
            },
        ),
        patch.object(
            metrics,
            "_fetch_usage_by_task",
            return_value={"diagnosis": {"call_count": 1, "total_tokens": 120}},
        ),
        patch.object(
            metrics,
            "_fetch_usage_by_call_type",
            return_value={"diagnosis.diagnosis": {"call_count": 1, "total_tokens": 120}},
        ),
        patch.object(
            metrics,
            "_fetch_usage_by_model",
            return_value={"test-model": {"call_count": 1, "total_tokens": 120}},
        ),
        patch.object(
            metrics,
            "_fetch_agent_turn_call_counts",
            return_value={
                "annotation.agent": 37,
                "diagnosis.diagnosis": 1,
            },
        ),
    ):
        stats = metrics.fetch_token_usage_stats(session, "run-1", "novel-1")

    assert stats["summary"]["accounting_method"] == "estimated"
    assert stats["summary"]["coverage_status"] == "partial"
    assert stats["coverage_gaps"] == ["annotation.agent"]


def test_fetch_token_usage_stats_marks_complete_when_counts_match() -> None:
    """
    2026-08-10 用于验证新 run 所有 Agent 回合都已入账时 coverage_status 为 complete。
    """
    session = MagicMock()
    with (
        patch.object(
            metrics,
            "_fetch_usage_summary",
            return_value={
                "call_count": 4,
                "total_prompt_tokens": 200,
                "total_completion_tokens": 40,
                "total_tokens": 240,
            },
        ),
        patch.object(
            metrics,
            "_fetch_usage_by_task",
            return_value={"annotation": {"call_count": 4, "total_tokens": 240}},
        ),
        patch.object(
            metrics,
            "_fetch_usage_by_call_type",
            return_value={"annotation.agent": {"call_count": 4, "total_tokens": 240}},
        ),
        patch.object(
            metrics,
            "_fetch_usage_by_model",
            return_value={"test-model": {"call_count": 4, "total_tokens": 240}},
        ),
        patch.object(
            metrics,
            "_fetch_agent_turn_call_counts",
            return_value={"annotation.agent": 4},
        ),
    ):
        stats = metrics.fetch_token_usage_stats(session, "run-1", "novel-1")

    assert stats["summary"]["coverage_status"] == "complete"
    assert stats["coverage_gaps"] == []


def test_agent_call_type_maps_annotation_and_diagnosis() -> None:
    """
    2026-08-10 用于验证新审计表任务类型到 token_usage 调用桶的稳定映射
    """
    assert metrics._agent_call_type("annotation") == "agent"
    assert metrics._agent_call_type("diagnosis") == "diagnosis"


def test_normalize_token_usage_task_type_keeps_current_task_names() -> None:
    """
    2026-08-05 用于验证 token 统计只保留当前业务任务名称
    """
    assert metrics._normalize_token_usage_task_type("annotation") == "annotation"
    assert metrics._normalize_token_usage_task_type("diagnosis") == "diagnosis"


def test_fetch_token_usage_stats_groups_current_task_buckets() -> None:
    """
    2026-08-05 用于验证当前 token_usage 任务桶按原始任务聚合
    """
    session = MagicMock()
    execute_result = MagicMock()
    execute_result.fetchall.return_value = [
        MagicMock(task_type="annotation", call_count=2, total_tokens=120),
        MagicMock(task_type="diagnosis", call_count=1, total_tokens=30),
    ]
    session.execute.return_value = execute_result

    stats = metrics._fetch_usage_by_task(session, "run-1", "novel-1")

    assert stats["annotation"]["call_count"] == 2
    assert stats["annotation"]["total_tokens"] == 120
    assert stats["diagnosis"]["call_count"] == 1
    assert stats["diagnosis"]["total_tokens"] == 30


def test_fetch_agent_turn_call_counts_ignores_error_turns() -> None:
    """
    2026-08-10 用于验证 coverage 分母只统计新审计表中成功回合
    """
    session = MagicMock()
    execute_result = MagicMock()
    execute_result.fetchall.return_value = [
        MagicMock(task_type="annotation", turn_count=2),
        MagicMock(task_type="diagnosis", turn_count=1),
    ]
    session.execute.return_value = execute_result

    counts = metrics._fetch_agent_turn_call_counts(session, "run-1")

    assert counts["annotation.agent"] == 2
    assert counts["diagnosis.diagnosis"] == 1


def test_insert_token_usage_writes_cache_cost_and_accounting_source() -> None:
    """
    2026-08-10 用于验证 token_usage 新列随记账写入
    """
    session = MagicMock()

    metrics.insert_token_usage(
        session,
        "run-1",
        "novel-1",
        "annotation",
        "agent",
        "model-x",
        prompt_tokens=100,
        total_tokens=120,
        completion_tokens=20,
        chapter_id=5,
        cache_read_tokens=30,
        cost=0.42,
        accounting_source="reported",
    )

    row = session.add.call_args.args[0]
    assert row.cache_read_tokens == 30
    assert row.cost == 0.42
    assert row.accounting_source == "reported"


def test_insert_token_usage_defaults_missing_cache_read_to_zero() -> None:
    """
    2026-08-10 用于验证无缓存证据时按全量计费记 0，费用留 NULL
    """
    session = MagicMock()

    metrics.insert_token_usage(
        session,
        "run-1",
        "novel-1",
        "annotation",
        "agent",
        "model-x",
        prompt_tokens=100,
        total_tokens=120,
    )

    row = session.add.call_args.args[0]
    assert row.cache_read_tokens == 0
    assert row.cost is None
    assert row.accounting_source == "reported"
