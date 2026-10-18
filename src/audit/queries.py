"""审计查询：用量统计、覆盖缺口与 Agent 回合读投影；只统计实际请求事实

2026-10-16 全库 3NF 改造；2026-10-17 六 agent 归属：审计事实全在
model_calls / agent_tool_calls 宽表上。run 内调用由执行的直接归属取得——
标注角色（annotation/entity/event/metric）与诊断角色（case/report）都直接
携带 run；非 Agent 调用按 standalone_* 上下文列取。用量分项与供应商实报总量
同列区分，total_tokens 优先实报、缺失才按分项投影；五类计时为具名列，
turn_ms 是 model_ms + tool_wall_ms 的读取投影。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.audit.documents import decode_document, decode_text_document
from src.storage import Storage
from src.storage.records.models import ModelCallRecord as ModelCall

_AGENT_CALL_BUCKETS: dict[str, tuple[str, str]] = {
    "annotation": ("annotation", "agent"),
    "diagnosis": ("diagnosis", "diagnosis"),
}
_TIMING_READ_COLUMNS: tuple[tuple[str, str], ...] = (
    ("ttft", "ttft_ms"),
    ("first_visible", "first_visible_ms"),
    ("reasoning", "reasoning_ms"),
    ("model", "model_ms"),
    ("tool_wall", "tool_wall_ms"),
)


def project_turn_ms(timings: dict[str, int]) -> int | None:
    """turn_ms 读投影：现有 model_ms 与 tool_wall_ms 的合计规则，两者都缺才为 NULL"""
    model_ms = timings.get("model")
    tool_wall_ms = timings.get("tool_wall")
    if model_ms is None and tool_wall_ms is None:
        return None
    return int(model_ms or 0) + int(tool_wall_ms or 0)


def project_total_tokens(
    *, reported_total_tokens: int | None, prompt_tokens: int | None, completion_tokens: int | None
) -> int | None:
    """total_tokens 读投影：优先供应商实报，缺失才按分项 fallback（不重复加 reasoning/cache）"""
    if reported_total_tokens is not None:
        return int(reported_total_tokens)
    if prompt_tokens is None and completion_tokens is None:
        return None
    return int(prompt_tokens or 0) + int(completion_tokens or 0)


@dataclass(frozen=True, slots=True)
class AuditedTurn:
    """Agent 回合读投影：model_calls 宽行（身份、用量、计时与四类观察文档同列）"""

    call_id: str
    execution_id: str
    turn_index: int
    model: str
    status: str
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    task_type: str
    call_type: str
    prompt_tokens: int | None
    completion_tokens: int | None
    cache_read_tokens: int | None
    reasoning_tokens: int | None
    total_tokens: int | None
    accounting_source: str | None
    cost: float | None
    timings: dict[str, int]
    timing_notes: tuple[str, ...]
    request_messages: list[Any] | None
    raw_response: dict[str, Any] | None
    context_summary: dict[str, Any] | None
    tool_wall_ms: int | None

    @property
    def turn_ms(self) -> int | None:
        """回合总耗时的现有合计规则投影"""
        return project_turn_ms(self.timings)


@dataclass(frozen=True, slots=True)
class AuditedToolCall:
    """工具调用读投影：agent_tool_calls 宽行（耗时与四类观察文档同列）"""

    tool_call_id: str
    call_id: str
    tool_name: str
    call_index: int
    status: str
    error: str | None
    started_at: datetime
    duration_ms: int | None
    executed_args: Any
    raw_args: str | None
    response_observed: Any
    receipt_observed: Any


def fetch_token_usage_stats(session: Storage, run_id: str) -> dict[str, Any]:
    """获取模型调用的 token 使用统计。"""
    summary = _fetch_usage_summary(session, run_id)
    by_task = _fetch_usage_by_task(session, run_id)
    by_call_type = _fetch_usage_by_call_type(session, run_id)
    by_model = _fetch_usage_by_model(session, run_id)
    coverage_gaps = _detect_token_coverage_gaps(session, run_id)
    sources = set(session.reads.audit_queries_fetch_token_usage_stats_1(run_id))
    summary["accounting_method"] = "unknown" if not sources else "reported" if sources == {"reported"} else "estimated"
    summary["coverage_scope"] = "实际审计请求及已记录的非 Agent 调用；未记录链路不能推断完整"
    summary["coverage_status"] = "partial" if coverage_gaps else "unknown" if not sources else "recorded_calls"
    return {
        "summary": summary,
        "by_task": by_task,
        "by_call_type": by_call_type,
        "by_model": by_model,
        "coverage_gaps": coverage_gaps,
    }


def _fetch_usage_summary(session: Storage, run_id: str) -> dict[str, Any]:
    """获取使用量摘要"""
    result = session.reads.audit_queries_fetch_usage_summary(run_id)
    if result is None:
        return {"call_count": 0, "total_prompt_tokens": 0, "total_completion_tokens": 0, "total_tokens": 0}
    return {
        "call_count": result.call_count or 0,
        "total_prompt_tokens": result.total_prompt_tokens or 0,
        "total_completion_tokens": result.total_completion_tokens or 0,
        "total_tokens": result.total_tokens or 0,
    }


def _fetch_usage_by_task(session: Storage, run_id: str) -> dict[str, Any]:
    """按任务类型获取使用量"""
    result = session.reads.audit_queries_fetch_usage_by_task(run_id)
    aggregated: dict[str, dict[str, int]] = {}
    for row in result:
        bucket = aggregated.setdefault(row.task_type, {"call_count": 0, "total_tokens": 0})
        bucket["call_count"] += int(row.call_count or 0)
        bucket["total_tokens"] += int(row.total_tokens or 0)
    return aggregated


def _build_call_type_key(task_type: str, call_type: str) -> str:
    """构建对外统一的调用桶 key"""
    return f"{task_type}.{call_type}"


def _fetch_usage_by_call_type(session: Storage, run_id: str) -> dict[str, Any]:
    """按 task_type + call_type 获取使用量"""
    result = session.reads.audit_queries_fetch_usage_by_call_type(run_id)
    aggregated: dict[str, dict[str, int]] = {}
    for row in result:
        key = _build_call_type_key(row.task_type, row.call_type)
        bucket = aggregated.setdefault(key, {"call_count": 0, "total_tokens": 0})
        bucket["call_count"] += int(row.call_count or 0)
        bucket["total_tokens"] += int(row.total_tokens or 0)
    return aggregated


def _fetch_usage_by_model(session: Storage, run_id: str) -> dict[str, Any]:
    """按模型获取使用量"""
    result = session.reads.audit_queries_fetch_usage_by_model(run_id)
    return {
        row.model: {"call_count": int(row.call_count or 0), "total_tokens": int(row.total_tokens or 0)}
        for row in result
    }


def _detect_token_coverage_gaps(session: Storage, run_id: str) -> list[str]:
    """找出计账口径不完整的 Agent 调用桶

    宽表落库后缺口有三类：尚未收口的 running 调用、没有用量分项的行、
    以及只能本地估算（非供应商实报）的行。
    """
    gaps: set[str] = set()
    for row in session.reads.audit_queries_detect_token_coverage_gaps_1(run_id):
        gaps.add(_build_call_type_key(row.task_type, row.call_type))
    return sorted(gaps)


def fetch_agent_turns(session: Storage, run_id: str) -> list[AuditedTurn]:
    """读取本 run 的 Agent 回合视图（按 call_id 先后排序）

    model_calls 宽行的 execution_id+turn_index 决定身份与回合序，用量分项/实报/
    费用/五类计时/计时备注/四类文档都取自同一行的具名列；四个 bytes 列缺值表示
    当时没有该观察，不伪造空文档。
    """
    calls = list(session.reads.audit_queries_fetch_agent_turns_2(run_id))
    if not calls:
        return []
    execution_ids = {str(call.execution_id) for call in calls}
    annotation_executions = set(session.reads.audit_queries_fetch_agent_turns_1(execution_ids))
    turns: list[AuditedTurn] = []
    for call in calls:
        execution_id = str(call.execution_id)
        if call.turn_index is None:
            raise RuntimeError(f"Agent 调用缺少回合序号: {call.call_id}")
        bucket = _AGENT_CALL_BUCKETS["annotation" if execution_id in annotation_executions else "diagnosis"]
        timings = _read_timings(call)
        turns.append(
            AuditedTurn(
                call_id=str(call.call_id),
                execution_id=execution_id,
                turn_index=int(call.turn_index),
                model=str(call.model),
                status=str(call.status),
                error=call.error,
                started_at=call.started_at,
                finished_at=call.finished_at,
                task_type=bucket[0],
                call_type=bucket[1],
                prompt_tokens=call.prompt_tokens,
                completion_tokens=call.completion_tokens,
                cache_read_tokens=call.cache_read_tokens,
                reasoning_tokens=call.reasoning_tokens,
                total_tokens=project_total_tokens(
                    reported_total_tokens=call.reported_total_tokens,
                    prompt_tokens=call.prompt_tokens,
                    completion_tokens=call.completion_tokens,
                ),
                accounting_source=None if call.accounting_source is None else str(call.accounting_source),
                cost=call.cost,
                timings=timings,
                timing_notes=_read_timing_notes(call.timing_notes_bytes),
                request_messages=_decoded(call.request_messages_bytes),
                raw_response=_decoded(call.raw_response_bytes),
                context_summary=_decoded(call.context_observed_bytes),
                tool_wall_ms=timings.get("tool_wall"),
            )
        )
    return turns


def fetch_run_tool_calls(session: Storage, run_id: str) -> list[AuditedToolCall]:
    """读取本 run 的工具调用视图（按 tool_call_id 先后排序）"""
    call_ids = [turn.call_id for turn in fetch_agent_turns(session, run_id)]
    if not call_ids:
        return []
    rows = session.reads.audit_queries_fetch_run_tool_calls_1(call_ids)
    return [
        AuditedToolCall(
            tool_call_id=str(tool_call.id),
            call_id=str(tool_call.call_id),
            tool_name=str(tool_call.tool_name),
            call_index=int(tool_call.call_index),
            status=str(tool_call.status),
            error=tool_call.error,
            started_at=tool_call.started_at,
            duration_ms=None if tool_call.tool_duration_ms is None else int(tool_call.tool_duration_ms),
            executed_args=_decoded(tool_call.executed_args_bytes),
            raw_args=_decoded_text(tool_call.raw_args_bytes),
            response_observed=_decoded(tool_call.response_observed_bytes),
            receipt_observed=_decoded(tool_call.receipt_observed_bytes),
        )
        for tool_call in rows
    ]


def _read_timings(call: ModelCall) -> dict[str, int]:
    """按实际测得的具名计时列构建读投影；缺测量不出现在字典里"""
    timings: dict[str, int] = {}
    for timing_kind, column in _TIMING_READ_COLUMNS:
        value = getattr(call, column)
        if value is not None:
            timings[timing_kind] = int(value)
    return timings


def _read_timing_notes(blob: bytes | None) -> tuple[str, ...]:
    """计时备注文档按原顺序读回（可重复文字）；缺文档表示当时没有备注"""
    if blob is None:
        return ()
    notes = decode_document(bytes(blob)) or []
    return tuple(str(note) for note in notes)


def _decoded(blob: bytes | None) -> Any:
    """文档缺值表示当时没有该观察，不伪造空文档"""
    return None if blob is None else decode_document(bytes(blob))


def _decoded_text(blob: bytes | None) -> str | None:
    """原始字符串观察按 UTF-8 原样读回"""
    return None if blob is None else decode_text_document(bytes(blob))


__all__ = [
    "AuditedToolCall",
    "AuditedTurn",
    "fetch_agent_turns",
    "fetch_run_tool_calls",
    "fetch_token_usage_stats",
    "project_total_tokens",
    "project_turn_ms",
]
