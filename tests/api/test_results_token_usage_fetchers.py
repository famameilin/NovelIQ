from __future__ import annotations

from src.api.routes.results_fetchers.fetchers import _fetch_token_usage_stats


class _StatsRepoStub:
    """
    结果页 token_usage fetcher 的最小 repo stub。

    创建时间: 2026-04-22
    创建者: Codex
    任务: unify-estimated-token-accounting
    """

    def fetch_token_usage_stats(self, run_id: str, novel_id: str) -> dict:
        assert run_id == "run-1"
        assert novel_id == "novel-1"
        return {
            "summary": {
                "call_count": 3,
                "total_prompt_tokens": 90,
                "total_completion_tokens": 30,
                "total_tokens": 120,
                "accounting_method": "estimated",
                "coverage_status": "partial",
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
    """
    创建时间: 2026-04-22
    创建者: Codex
    任务: unify-estimated-token-accounting
    说明: fetcher 应把新的 accounting / coverage / by_call_type 字段完整暴露给 API。
    """
    stats = _fetch_token_usage_stats("run-1", "novel-1", _StatsRepoStub())

    assert stats.summary.accounting_method == "estimated"
    assert stats.summary.coverage_status == "partial"
    assert stats.by_call_type["annotation.phase3"].call_count == 2
    assert stats.coverage_gaps == ["annotation.phase4"]


class _FailingStatsRepoStub:
    def fetch_token_usage_stats(self, run_id: str, novel_id: str) -> dict:
        assert run_id == "run-1"
        assert novel_id == "novel-1"
        raise RuntimeError("boom")


def test_fetch_token_usage_stats_marks_partial_when_stats_fetch_fails() -> None:
    """
    创建时间: 2026-04-30
    任务: fix-level3-query-example-review-findings
    说明: token stats 查询失败时，fetcher 不能假装 coverage complete；
          至少要把结果标成 partial，并暴露明确的 unavailable gap。
    """
    stats = _fetch_token_usage_stats("run-1", "novel-1", _FailingStatsRepoStub())

    assert stats.summary.coverage_status == "partial"
    assert stats.coverage_gaps == ["token_usage_stats_unavailable"]
