"""
annotation phase runtime 单元测试。

创建时间: 2026-04-23
任务: annotation-projector-runtime-landing
说明: 覆盖薄执行器的 thinking 持久化、reasoning token、token 归桶与无 choices 结构化响应兜底。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.local.annotation.runtime import AnnotationPhaseCallSpec, execute_phase_call
from src.models.local.schema import ForeshadowingResult


def _make_client() -> MagicMock:
    """构造 runtime 测试用 annotation client mock。"""
    client = MagicMock()
    client._config = SimpleNamespace(model="test-model", thinking_enabled=True)
    client._is_cloud_api.return_value = False
    client._session = None
    client._extract_reasoning_tokens.return_value = 17
    client._record_estimated_token_usage_from_messages = MagicMock()
    client._record_estimated_token_usage_from_response = MagicMock()
    return client


@pytest.mark.asyncio
async def test_execute_phase_call_records_thinking_and_reasoning_tokens() -> None:
    """runtime 应持久化 response processing 提取出的 thinking 与 reasoning token。"""
    client = _make_client()
    parsed = ForeshadowingResult(
        has_foreshadowing=True,
        is_strong_setup=True,
        foreshadowing_type="物件",
        setup_kind="异常物件",
        anchor_text="铜铃",
        anchor_reason="反复出现但用途未明",
        setup_summary="铜铃反复出现且用途未明，后续可能触发异常能力",
        why_unresolved_now="当前还没有解释铜铃为何反复出现。",
        expected_payoff_family="能力触发",
        payoff_likelihood="high",
        is_new_setup=True,
        linked_setup_id=None,
        setup_status="open",
        confidence="high",
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="{}", reasoning_content="想法"))]
    )
    client._call_annotation_api = AsyncMock(return_value=(parsed, response))
    client._process_annotation_response.return_value = ("clean json", "runtime thinking", MagicMock())

    with patch("src.models.local.annotation.runtime.record_model_interaction") as mock_record:
        result = await execute_phase_call(
            client,
            AnnotationPhaseCallSpec(
                phase="phase2",
                interaction_type="annotate",
                call_type="phase2",
                messages=[{"role": "user", "content": "文本"}],
                response_model=ForeshadowingResult,
                chunk_id=3,
                run_id="run-1",
                attempt_number=2,
            ),
        )

    assert result.parsed is parsed
    assert result.content_clean == "clean json"
    assert result.thinking_content == "runtime thinking"
    assert result.reasoning_tokens == 17
    assert mock_record.call_args.kwargs["thinking_content"] == "runtime thinking"
    assert mock_record.call_args.kwargs["reasoning_tokens"] == 17
    assert mock_record.call_args.kwargs["attempt_number"] == 2
    client._record_estimated_token_usage_from_messages.assert_called_once()
    assert client._record_estimated_token_usage_from_messages.call_args.kwargs["task_type"] == "annotation"


@pytest.mark.asyncio
async def test_execute_phase_call_uses_structured_fallback_without_choices() -> None:
    """response 没有 choices 时，runtime 应使用 parsed.model_dump 作为记录文本。"""
    client = _make_client()
    parsed = ForeshadowingResult(
        has_foreshadowing=False,
        is_strong_setup=False,
        foreshadowing_type=None,
        anchor_text="",
        anchor_reason="",
        why_unresolved_now="",
        expected_payoff_family="",
        confidence="low",
    )
    response = SimpleNamespace(thinking_content="direct thinking")
    client._call_annotation_api = AsyncMock(return_value=(parsed, response))

    with patch("src.models.local.annotation.runtime.record_model_interaction") as mock_record:
        result = await execute_phase_call(
            client,
            AnnotationPhaseCallSpec(
                phase="phase2",
                interaction_type="annotate",
                call_type="phase2",
                messages=[{"role": "user", "content": "文本"}],
                response_model=ForeshadowingResult,
            ),
        )

    assert result.content_clean == str(parsed.model_dump())
    assert result.thinking_content == "direct thinking"
    client._process_annotation_response.assert_not_called()
    assert mock_record.call_args.kwargs["response_text"] == str(parsed.model_dump())


@pytest.mark.asyncio
async def test_execute_phase_call_records_response_usage_when_processing_fails() -> None:
    """response processing 或记录阶段失败时，应按 response 兜底补记 token。"""
    client = _make_client()
    parsed = ForeshadowingResult(
        has_foreshadowing=False,
        is_strong_setup=False,
        foreshadowing_type=None,
        anchor_text="",
        anchor_reason="",
        why_unresolved_now="",
        expected_payoff_family="",
        confidence="low",
    )
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}", reasoning_content=None))])
    client._call_annotation_api = AsyncMock(return_value=(parsed, response))
    client._process_annotation_response.side_effect = RuntimeError("bad response")

    with pytest.raises(RuntimeError):
        await execute_phase_call(
            client,
            AnnotationPhaseCallSpec(
                phase="phase4",
                interaction_type="relation_extraction",
                call_type="phase4",
                messages=[{"role": "user", "content": "文本"}],
                response_model=ForeshadowingResult,
                chunk_id=9,
            ),
        )

    client._record_estimated_token_usage_from_response.assert_called_once()
    assert client._record_estimated_token_usage_from_response.call_args.kwargs["task_type"] == "annotation"
