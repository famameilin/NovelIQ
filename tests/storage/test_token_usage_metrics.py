from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.storage.repositories.stats import metrics


def test_fetch_token_usage_stats_marks_partial_when_annotation_chain_is_missing() -> None:
    """
    创建时间: 2026-04-22
    任务: unify-estimated-token-accounting
    说明: 如果 model_interactions 里存在 annotation 主链调用，但 token_usage 没有对应桶，
          summary 必须标记为 partial，并暴露 coverage_gaps。
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
            "_fetch_model_interaction_call_counts",
            return_value={
                "annotation.phase1": 37,
                "annotation.phase2": 37,
                "diagnosis.diagnosis": 1,
            },
        ),
    ):
        stats = metrics.fetch_token_usage_stats(session, "run-1", "novel-1")

    assert stats["summary"]["accounting_method"] == "estimated"
    assert stats["summary"]["coverage_status"] == "partial"
    assert stats["coverage_gaps"] == ["annotation.phase1", "annotation.phase2"]


def test_fetch_token_usage_stats_marks_complete_when_counts_match() -> None:
    """
    创建时间: 2026-04-22
    任务: unify-estimated-token-accounting
    说明: 新 run 所有调用都已入账时，coverage_status 应为 complete。
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
            return_value={
                "annotation.phase1": {"call_count": 1, "total_tokens": 60},
                "annotation.phase2": {"call_count": 1, "total_tokens": 60},
                "annotation.phase3": {"call_count": 1, "total_tokens": 60},
                "annotation.phase4": {"call_count": 1, "total_tokens": 60},
            },
        ),
        patch.object(
            metrics,
            "_fetch_usage_by_model",
            return_value={"test-model": {"call_count": 4, "total_tokens": 240}},
        ),
        patch.object(
            metrics,
            "_fetch_model_interaction_call_counts",
            return_value={
                "annotation.phase1": 1,
                "annotation.phase2": 1,
                "annotation.phase3": 1,
                "annotation.phase4": 1,
            },
        ),
    ):
        stats = metrics.fetch_token_usage_stats(session, "run-1", "novel-1")

    assert stats["summary"]["coverage_status"] == "complete"
    assert stats["coverage_gaps"] == []


def test_normalize_model_interaction_call_key_maps_mainline_calls() -> None:
    """
    创建时间: 2026-04-22
    任务: unify-estimated-token-accounting
    说明: coverage 比较依赖 interaction -> call_type 的稳定映射，主链 key 不能漂移。
    """
    assert metrics._normalize_model_interaction_call_key("annotate", "phase1") == "annotation.phase1"
    assert (
        metrics._normalize_model_interaction_call_key("dialogue_attribution", "phase3") == "annotation.phase3"
    )
    assert metrics._normalize_model_interaction_call_key("stage_summary", "incremental") == (
        "incremental_disambig.stage_summary"
    )
    assert (
        metrics._normalize_model_interaction_call_key("disambiguate", "final_disambiguation")
        == "full_disambig.disambiguate_characters"
    )
    assert (
        metrics._normalize_model_interaction_call_key("level3_query_planner", "level3_query_planner")
        == "mention_extraction.level3_query_planner"
    )


def test_normalize_token_usage_task_type_maps_annotation_fallback_back_to_mainline() -> None:
    """
    创建时间: 2026-04-22
    任务: fix-token-coverage-fallback-bucket
    说明: fallback 标注客户端只是执行通道，不应在 coverage 统计里形成新的业务桶。
    """
    assert metrics._normalize_token_usage_task_type("annotation_fallback") == "annotation"
    assert metrics._normalize_token_usage_task_type("diagnosis") == "diagnosis"


def test_fetch_token_usage_stats_can_merge_fallback_task_bucket() -> None:
    """
    创建时间: 2026-04-22
    任务: fix-token-coverage-fallback-bucket
    说明: 即使旧 token_usage 里残留 annotation_fallback，汇总后的业务 task 桶也应合并回 annotation。
    """
    session = MagicMock()
    execute_result = MagicMock()
    execute_result.fetchall.return_value = [
        MagicMock(task_type="annotation", call_count=2, total_tokens=120),
        MagicMock(task_type="annotation_fallback", call_count=1, total_tokens=30),
    ]
    session.execute.return_value = execute_result

    stats = metrics._fetch_usage_by_task(session, "run-1", "novel-1")

    assert stats["annotation"]["call_count"] == 3
    assert stats["annotation"]["total_tokens"] == 150
    assert "annotation_fallback" not in stats


def test_fetch_model_interaction_call_counts_ignores_error_placeholders() -> None:
    """
    创建时间: 2026-04-22
    任务: fix-token-coverage-status
    说明: coverage 分母只能统计成功拿到响应的交互，重试错误占位记录必须忽略。
    """
    session = MagicMock()
    execute_result = MagicMock()
    execute_result.fetchall.return_value = [
        MagicMock(
            interaction_type="disambiguate",
            phase="incremental_disambiguation",
            status="success",
            call_count=2,
        ),
        MagicMock(
            interaction_type="disambiguate",
            phase="incremental_disambiguation",
            status="error",
            call_count=3,
        ),
    ]
    session.execute.return_value = execute_result

    counts = metrics._fetch_model_interaction_call_counts(session, "run-1")

    assert counts["incremental_disambig.disambiguate_characters"] == 2
