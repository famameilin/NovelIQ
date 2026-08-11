"""
Agent 回合审计观察器

说明: 图节点在模型请求与工具执行的关键点调用观察器，
观察器把完整回合与工具审计写入 AgentAuditRecorder（独立短事务）。
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from langchain_core.messages import AIMessage

from src.agents.audit.recorder import AgentAuditRecorder
from src.agents.stream import ModelCallTiming
from src.agents.usage import estimate_agent_token_usage, extract_agent_token_usage

_FALLBACK_AI_MESSAGE = AIMessage(content="")


def _extract_reasoning_content(message: Any) -> str:
    """2026-08-10 用于从完整响应探测模型思考内容（Qwen 系 reasoning_content）"""
    additional = getattr(message, "additional_kwargs", None) or {}
    reasoning = additional.get("reasoning_content") or additional.get("reasoning") or ""
    if reasoning:
        return str(reasoning)
    metadata = getattr(message, "response_metadata", None) or {}
    reasoning = metadata.get("reasoning_content") or metadata.get("reasoning") or ""
    if reasoning:
        return str(reasoning)
    direct = getattr(message, "reasoning_content", None)
    if direct:
        return str(direct)
    return ""


def _extract_finish_reason(message: Any) -> str:
    """2026-08-11 用于从完整响应探测流结束原因（聚合器挂在 additional_kwargs，非流式在 metadata）"""
    additional = getattr(message, "additional_kwargs", None) or {}
    finish_reason = additional.get("finish_reason")
    if finish_reason:
        return str(finish_reason)
    metadata = getattr(message, "response_metadata", None) or {}
    finish_reason = metadata.get("finish_reason")
    if finish_reason:
        return str(finish_reason)
    return ""


def _serialize_ai_message(message: Any) -> dict[str, Any]:
    """2026-08-10 用于把单条模型回复压缩为审计可持久化结构（含正文与思考内容）"""
    payload: dict[str, Any] = {
        "role": str(getattr(message, "type", "unknown")),
        "content": str(getattr(message, "content", "") or ""),
    }
    reasoning = _extract_reasoning_content(message)
    if reasoning:
        payload["reasoning_content"] = reasoning
    finish_reason = _extract_finish_reason(message)
    if finish_reason:
        payload["finish_reason"] = finish_reason
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        payload["tool_calls"] = tool_calls
    name = getattr(message, "name", None)
    if name:
        payload["name"] = name
    return payload


def _serialize_request_messages(messages: list[Any]) -> list[dict[str, Any]]:
    """2026-08-11 用于把请求消息序列化为可持久化结构，支持完整重放一次模型请求"""
    serialized: list[dict[str, Any]] = []
    if not messages:
        return serialized
    for message in messages:
        payload: dict[str, Any] = {
            "role": str(getattr(message, "type", "unknown")),
            "content": str(getattr(message, "content", "") or ""),
        }
        name = getattr(message, "name", None)
        if name:
            payload["name"] = str(name)
        tool_call_id = getattr(message, "tool_call_id", None)
        if tool_call_id:
            payload["tool_call_id"] = str(tool_call_id)
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            payload["tool_calls"] = tool_calls
        reasoning = _extract_reasoning_content(message)
        if reasoning:
            payload["reasoning_content"] = reasoning
        serialized.append(payload)
    return serialized


def _usage_for_turn(request_messages: list[Any], response_message: Any) -> dict[str, Any] | None:
    """2026-08-10 用于优先取 Provider 用量，缺失时按本地估算兜底"""
    usage = extract_agent_token_usage(response_message)
    if usage is None:
        estimates = estimate_agent_token_usage([*request_messages, response_message])
        usage = estimates[0] if estimates else None
    if usage is None:
        return None
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cost": usage.cost,
        "reasoning_tokens": usage.reasoning_tokens,
        "accounting_source": "estimated" if usage.estimated else "reported",
    }


class AgentTurnObserver:
    """2026-08-10 用于在 Agent 图节点间传递当前回合审计上下文并逐笔落库"""

    def __init__(
        self,
        recorder: AgentAuditRecorder,
        *,
        invocation_id: int,
        run_id: str,
        novel_id: str,
        task_type: str,
        call_type: str,
        model_name: str,
        model_provider: str,
    ) -> None:
        """2026-08-10 用于绑定审计库与本次尝试的运行元数据"""
        self._recorder = recorder
        self._invocation_id = invocation_id
        self._run_id = run_id
        self._novel_id = novel_id
        self._task_type = task_type
        self._call_type = call_type
        self._model_name = model_name or "unknown"
        self._model_provider = model_provider
        self._turn_counter = 0
        self._active_turn_id: int | None = None
        self._active_started_ns: int | None = None
        self._active_tool_first_ns: int | None = None
        self._active_tool_last_ns: int | None = None

    def record_turn(
        self,
        *,
        turn_index: int | None = None,
        context_summary: dict[str, Any],
        request_messages: list[Any],
        response_message: Any,
        timing: ModelCallTiming,
        started_ns: int,
        status: str = "success",
        error: str | None = None,
    ) -> int:
        """2026-08-10 用于写入模型回合与 Token 行并激活工具审计上下文"""
        self._turn_counter = turn_index or self._turn_counter + 1
        turn_id = self._recorder.record_turn(
            invocation_id=self._invocation_id,
            turn_index=self._turn_counter,
            context_summary=context_summary,
            raw_response=_serialize_ai_message(response_message),
            status=status,
            error=error,
            timing={
                "ttft_ms": timing.ttft_ms,
                "first_visible_ms": timing.first_visible_ms,
                "reasoning_ms": timing.reasoning_ms,
                "model_ms": timing.model_ms,
            },
            timing_notes=list(timing.timing_notes),
            request_messages=_serialize_request_messages(request_messages),
            token_usage=_usage_for_turn(request_messages, response_message),
            run_id=self._run_id,
            novel_id=self._novel_id,
            task_type=self._task_type,
            call_type=self._call_type,
            model=self._model_name,
        )
        self._active_turn_id = turn_id
        self._active_started_ns = started_ns
        self._active_tool_first_ns = None
        self._active_tool_last_ns = None
        return turn_id

    def record_tool_call(
        self,
        *,
        call_index: int,
        tool_name: str,
        request_args: Mapping[str, Any],
        response: dict[str, Any] | None,
        receipt: dict[str, Any] | None,
        status: str,
        error: str | None,
        tool_duration_ms: int | None,
        started_ns: int,
    ) -> None:
        """2026-08-10 用于写入单次工具调用审计并累计工具墙钟区间"""
        if self._active_turn_id is None:
            raise RuntimeError("工具审计必须先于模型回合写入 turn 行")
        self._recorder.record_tool_call(
            turn_id=self._active_turn_id,
            call_index=call_index,
            tool_name=tool_name,
            request_args=dict(request_args),
            response=response,
            receipt=receipt,
            status=status,
            error=error,
            tool_duration_ms=tool_duration_ms,
        )
        if self._active_tool_first_ns is None:
            self._active_tool_first_ns = started_ns
        self._active_tool_last_ns = max(
            self._active_tool_last_ns or 0,
            started_ns + int(tool_duration_ms or 0) * 1_000_000,
        )

    def record_failed_turn(
        self,
        *,
        context_summary: dict[str, Any],
        error: str,
        started_ns: int,
        request_messages: list[Any] | None = None,
    ) -> None:
        """2026-08-11 用于在模型调用异常时保留 error 状态回合并立即闭合计时"""
        self.record_turn(
            context_summary=context_summary,
            request_messages=request_messages or [],
            response_message=_FALLBACK_AI_MESSAGE,
            timing=ModelCallTiming(
                model_ms=max(0, round((time.perf_counter_ns() - started_ns) / 1_000_000)),
                timing_notes=("provider_call_failed",),
            ),
            started_ns=started_ns,
            status="error",
            error=error,
        )
        self.close_turn()

    def close_turn(self) -> None:
        """2026-08-10 用于在全部 ToolReceipt 构造完成后补写工具墙钟与回合总耗时"""
        if self._active_turn_id is None:
            return
        now_ns = time.perf_counter_ns()
        tool_wall_ms: int | None = None
        if self._active_tool_first_ns is not None and self._active_tool_last_ns is not None:
            tool_wall_ms = max(0, round((self._active_tool_last_ns - self._active_tool_first_ns) / 1_000_000))
        turn_ms = max(0, round((now_ns - (self._active_started_ns or now_ns)) / 1_000_000))
        self._recorder.update_turn_timings(
            self._active_turn_id,
            tool_wall_ms=tool_wall_ms,
            turn_ms=turn_ms,
        )
        self._active_turn_id = None
        self._active_started_ns = None
        self._active_tool_first_ns = None
        self._active_tool_last_ns = None


__all__ = ["AgentTurnObserver"]
