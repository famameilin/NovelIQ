from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from src.api.services.results_queries.metadata import _fetch_token_usage_stats as serialize_token_usage


def _fetch_token_usage_stats(run_id, source):
    """在实际领域查询点注入用量，继续验证 HTTP 载荷的完整字段"""
    with patch(
        "src.api.services.results_queries.metadata.fetch_token_usage_stats",
        side_effect=lambda session, identifier: source.fetch_token_usage_stats(identifier),
    ):
        return serialize_token_usage(run_id, SimpleNamespace(session=object()))


class _StatsRepoStub:
    """结果页 token_usage fetcher 的最小 repo stub。"""

    def fetch_token_usage_stats(self, run_id: str) -> dict:
        assert run_id == "run-1"
        return {
            "summary": {
                "call_count": 3,
                "total_prompt_tokens": 90,
                "total_completion_tokens": 30,
                "total_tokens": 120,
                "accounting_method": "estimated",
                "coverage_status": "partial",
                "coverage_scope": "实际审计请求与已记录的非 Agent 调用",
            },
            "by_task": {
                "annotation": {"call_count": 2, "total_tokens": 80},
            },
            "by_call_type": {
                "annotation.phase3": {"call_count": 2, "total_tokens": 80},
                "diagnosis.diagnosis": {"call_count": 1, "total_tokens": 40},
            },
            "by_model": {
                "test-model": {"call_count": 3, "total_tokens": 120},
            },
            "coverage_gaps": ["annotation.phase4"],
        }


def test_fetch_token_usage_stats_exposes_coverage_fields() -> None:
    """fetcher 应把新的 accounting / coverage / by_call_type 字段完整暴露给 API。"""
    stats = _fetch_token_usage_stats("run-1", _StatsRepoStub())

    assert stats.summary.accounting_method == "estimated"
    assert stats.summary.coverage_status == "partial"
    assert stats.summary.coverage_scope == "实际审计请求与已记录的非 Agent 调用"
    assert stats.by_call_type["annotation.phase3"].call_count == 2
    assert stats.coverage_gaps == ["annotation.phase4"]


class _FailingStatsRepoStub:
    def fetch_token_usage_stats(self, run_id: str) -> dict:
        assert run_id == "run-1"
        raise RuntimeError("boom")


def test_fetch_token_usage_stats_marks_partial_when_stats_fetch_fails() -> None:
    """至少要把结果标成 partial，并暴露明确的 unavailable gap。"""
    stats = _fetch_token_usage_stats("run-1", _FailingStatsRepoStub())

    assert stats.summary.coverage_status == "partial"
    assert stats.coverage_gaps == ["token_usage_stats_unavailable"]


def test_reported_usage_and_recorded_call_scope_survive_api_serialization() -> None:
    from types import SimpleNamespace

    source = _StatsRepoStub().fetch_token_usage_stats("run-1")
    source["summary"].update(accounting_method="reported", coverage_status="recorded_calls")
    source["coverage_gaps"] = []
    result = _fetch_token_usage_stats("run-1", SimpleNamespace(fetch_token_usage_stats=lambda *_: source))

    assert result.summary.total_tokens == 120
    assert result.summary.call_count == 3
    assert result.summary.accounting_method == "reported"
    assert result.summary.coverage_status == "recorded_calls"
    assert result.summary.coverage_scope == source["summary"]["coverage_scope"]
    assert result.by_model["test-model"].total_tokens == 120


def test_missing_usage_stays_unknown_instead_of_claiming_complete() -> None:
    from types import SimpleNamespace

    source = {
        "summary": {
            "call_count": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_tokens": 0,
            "accounting_method": "unknown",
            "coverage_status": "unknown",
            "coverage_scope": "未记录链路不能推断完整",
        },
        "by_task": {},
        "by_model": {},
        "by_call_type": {},
        "coverage_gaps": [],
    }
    result = _fetch_token_usage_stats("run-1", SimpleNamespace(fetch_token_usage_stats=lambda *_: source))
    assert result.summary.accounting_method == "unknown"
    assert result.summary.coverage_status == "unknown"
    assert result.coverage_gaps == []
