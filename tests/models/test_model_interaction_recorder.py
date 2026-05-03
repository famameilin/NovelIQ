"""
创建时间: 2026-04-22
任务: distinguish-thinking-visibility
说明: 回归测试模型交互记录器对 thinking 可见性状态的判定。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.models.interactions.recorder import record_model_interaction


def _build_messages() -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user prompt"},
    ]


def test_record_model_interaction_marks_tokens_only_when_reasoning_tokens_exist() -> None:
    """
    创建时间: 2026-04-22
    任务: distinguish-thinking-visibility
    说明: 没有 thinking 文本但 reasoning_tokens > 0 时，应明确记成 tokens_only。
    """
    mock_repo = MagicMock()
    mock_repo.save_interaction = MagicMock()

    with patch(
        "src.storage.repositories.model_interaction_repository.ModelInteractionRepository",
        return_value=mock_repo,
    ):
        record_model_interaction(
            run_id="run-1",
            chunk_id=1,
            interaction_type="diagnose",
            phase="diagnose",
            attempt_number=1,
            messages=_build_messages(),
            response_text="{}",
            thinking_content=None,
            reasoning_tokens=19,
            requested_thinking=True,
            duration_ms=12,
            model_name="test-model",
            model_provider="cloud",
            session=object(),
        )

    kwargs = mock_repo.save_interaction.call_args.kwargs
    assert kwargs["reasoning_tokens"] == 19
    assert kwargs["thinking_state"] == "tokens_only"


def test_record_model_interaction_marks_none_when_thinking_disabled() -> None:
    """
    创建时间: 2026-04-22
    任务: distinguish-thinking-visibility
    说明: 本次调用明确没请求 think 时，即使没有 reasoning token，也应记录为 none。
    """
    mock_repo = MagicMock()
    mock_repo.save_interaction = MagicMock()

    with patch(
        "src.storage.repositories.model_interaction_repository.ModelInteractionRepository",
        return_value=mock_repo,
    ):
        record_model_interaction(
            run_id="run-1",
            chunk_id=1,
            interaction_type="stage_summary",
            phase="incremental",
            attempt_number=1,
            messages=_build_messages(),
            response_text="summary",
            thinking_content=None,
            reasoning_tokens=None,
            requested_thinking=False,
            duration_ms=12,
            model_name="test-model",
            model_provider="local",
            session=object(),
        )

    kwargs = mock_repo.save_interaction.call_args.kwargs
    assert kwargs["reasoning_tokens"] is None
    assert kwargs["thinking_state"] == "none"


def test_record_model_interaction_preserves_error_status() -> None:
    """
    创建时间: 2026-04-22
    任务: fix-token-coverage-status
    说明: 重试链路写入的 error 占位记录必须保留 error 状态，
          后续 coverage 才能排除这些并未拿到真实响应的调用。
    """
    mock_repo = MagicMock()
    mock_repo.save_interaction = MagicMock()

    with patch(
        "src.storage.repositories.model_interaction_repository.ModelInteractionRepository",
        return_value=mock_repo,
    ):
        record_model_interaction(
            run_id="run-1",
            chunk_id=None,
            interaction_type="disambiguate",
            phase="incremental_disambiguation",
            attempt_number=2,
            messages=_build_messages(),
            response_text='{"error":"timeout"}',
            thinking_content=None,
            reasoning_tokens=None,
            requested_thinking=True,
            duration_ms=1200,
            model_name="test-model",
            model_provider="local",
            status="error",
            error_message="timeout",
            session=object(),
        )

    kwargs = mock_repo.save_interaction.call_args.kwargs
    assert kwargs["status"] == "error"
    assert kwargs["error_message"] == "timeout"
