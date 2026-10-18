from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.agents.turn_observer import build_invocation_context
from src.audit import queries as metrics
from tests.support.storage_fixtures import fixture_id


def test_fetch_token_usage_stats_reports_unknown_without_rows() -> None:
    """验证无任何计账行时 summary 标记 unknown 且无缺口"""
    session = MagicMock()
    session.reads.audit_queries_fetch_token_usage_stats_1.return_value = []
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
        patch.object(metrics, "_detect_token_coverage_gaps", return_value=[]),
    ):
        stats = metrics.fetch_token_usage_stats(session, fixture_id(__name__, "run-1"))

    assert stats["summary"]["accounting_method"] == "unknown"
    assert stats["summary"]["coverage_status"] == "unknown"
    assert stats["coverage_gaps"] == []


def test_fetch_token_usage_stats_marks_partial_when_gaps_exist() -> None:
    """验证存在覆盖缺口时 coverage_status 标记 partial 并透出缺口桶"""
    session = MagicMock()
    session.reads.audit_queries_fetch_token_usage_stats_1.return_value = []
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
            "_detect_token_coverage_gaps",
            return_value=["annotation.agent"],
        ),
    ):
        stats = metrics.fetch_token_usage_stats(session, fixture_id(__name__, "run-1"))

    assert stats["summary"]["coverage_status"] == "partial"
    assert stats["coverage_gaps"] == ["annotation.agent"]


def test_build_invocation_context_maps_annotation_to_agent_call_type() -> None:
    """验证审计任务类型到计账桶 call_type 的稳定映射"""
    annotation = build_invocation_context(
        run_id=fixture_id(__name__, "run-1"),
        task_type="annotation",
        execution_id=fixture_id(__name__, "exec-1"),
        attempt_number=1,
        model="test-model",
        chapter_id=1,
        role="annotation",
    )
    assert annotation["call_type"] == "agent"
    diagnosis = build_invocation_context(
        run_id=fixture_id(__name__, "run-1"),
        task_type="diagnosis",
        execution_id=fixture_id(__name__, "exec-2"),
        attempt_number=1,
        model="test-model",
        role="case",
        case_anchor="case-1",
    )
    assert diagnosis["call_type"] == "diagnosis"


def test_fetch_usage_by_task_groups_current_task_buckets() -> None:
    """验证当前 token 统计任务桶按原始任务聚合"""
    session = MagicMock()
    session.reads.audit_queries_fetch_token_usage_stats_1.return_value = []
    execute_result = MagicMock()
    execute_result.fetchall.return_value = [
        SimpleNamespace(task_type="annotation", call_count=2, total_tokens=120),
        SimpleNamespace(task_type="diagnosis", call_count=1, total_tokens=30),
    ]
    session.reads.audit_queries_fetch_usage_by_task.return_value = execute_result.fetchall.return_value

    stats = metrics._fetch_usage_by_task(session, fixture_id(__name__, "run-1"))

    assert stats["annotation"]["call_count"] == 2
    assert stats["annotation"]["total_tokens"] == 120
    assert stats["diagnosis"]["call_count"] == 1
    assert stats["diagnosis"]["total_tokens"] == 30


def test_detect_token_coverage_gaps_reports_unclosed_and_unaccounted_rows() -> None:
    """验证 running、缺计账与本地估算的回合按调用桶报缺口"""
    session = MagicMock()
    session.reads.audit_queries_fetch_token_usage_stats_1.return_value = []
    session.reads.audit_queries_detect_token_coverage_gaps_1.return_value = [
        SimpleNamespace(task_type="annotation", call_type="agent"),
        SimpleNamespace(task_type="diagnosis", call_type="diagnosis"),
    ]

    gaps = metrics._detect_token_coverage_gaps(session, fixture_id(__name__, "run-1"))

    assert gaps == ["annotation.agent", "diagnosis.diagnosis"]
