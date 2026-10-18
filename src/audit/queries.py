"""审计查询：用量统计、覆盖缺口与 Agent 回合读投影；只统计实际请求事实

审计事实全在 model_calls / agent_tool_calls 宽表上：run 内调用由执行的直接
归属取得，非 Agent 调用按 standalone_* 上下文列取。total_tokens 优先供应商
实报、缺失才按分项投影；turn_ms 是 model_ms + tool_wall_ms 的读取投影。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CompoundSelect, Select, func, literal, select, union_all
from sqlalchemy.orm import Session

from src.audit.documents import decode_document, decode_text_document
from src.storage.models import AgentToolCall, Execution, ModelCall
from src.storage.models.work import ANNOTATION_ROLES, DIAGNOSIS_ROLES

# Agent 调用的计账桶由执行角色唯一决定（执行行直接携带归属）
_AGENT_CALL_BUCKETS: dict[str, tuple[str, str]] = {
    "annotation": ("annotation", "agent"),
    "diagnosis": ("diagnosis", "diagnosis"),
}

#: model_calls 的五类计时列 → 审计读投影计时类别（turn_ms 由 model+tool_wall 合计）
_TIMING_READ_COLUMNS: tuple[tuple[str, str], ...] = (
    ("ttft", "ttft_ms"),
    ("first_visible", "first_visible_ms"),
    ("reasoning", "reasoning_ms"),
    ("model", "model_ms"),
    ("tool_wall", "tool_wall_ms"),
)


def _annotation_execution_ids(run_id: str) -> Select[Any]:
    """本 run 章内标注执行的 execution_id 选择器（执行行直接带 run 与标注角色）"""
    return select(Execution.execution_id).where(
        Execution.run_id == run_id, Execution.role.in_(ANNOTATION_ROLES)
    )


def _diagnosis_execution_ids(run_id: str) -> Select[Any]:
    """本 run 诊断执行（案例/报告角色）的 execution_id 选择器（执行行直接带 run）"""
    return select(Execution.execution_id).where(
        Execution.run_id == run_id, Execution.role.in_(DIAGNOSIS_ROLES)
    )


def run_agent_execution_ids(run_id: str) -> Select[tuple[str]]:
    """本 run 内 Agent 执行的 execution_id 选择器（两类执行归属的直接并集）"""
    return cast(
        "Select[tuple[str]]", _annotation_execution_ids(run_id).union(_diagnosis_execution_ids(run_id))
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

    call_id: int
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

    tool_call_id: int
    call_id: int
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


def fetch_token_usage_stats(session: Session, run_id: str) -> dict[str, Any]:
    """获取模型调用的 token 使用统计。"""
    summary = _fetch_usage_summary(session, run_id)
    by_task = _fetch_usage_by_task(session, run_id)
    by_call_type = _fetch_usage_by_call_type(session, run_id)
    by_model = _fetch_usage_by_model(session, run_id)
    coverage_gaps = _detect_token_coverage_gaps(session, run_id)
    # estimated 表示整套 token 统计只作近似成本信号，单条记录仍优先复用 provider 实报值
    calls = _usage_calls(run_id)
    sources = set(
        session.execute(
            select(calls.c.accounting_source).where(calls.c.accounting_source.is_not(None))
        ).scalars()
    )
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


def _agent_call_columns(task_type: str, call_type: str) -> list[Any]:
    """Agent 调用的统一列面：调用身份、计账桶与用量/实报投影来源"""
    return [
        ModelCall.call_id.label("call_id"),
        ModelCall.model.label("model"),
        ModelCall.status.label("status"),
        literal(task_type).label("task_type"),
        literal(call_type).label("call_type"),
        ModelCall.prompt_tokens.label("prompt_tokens"),
        ModelCall.completion_tokens.label("completion_tokens"),
        ModelCall.cache_read_tokens.label("cache_read_tokens"),
        ModelCall.reasoning_tokens.label("reasoning_tokens"),
        ModelCall.accounting_source.label("accounting_source"),
        ModelCall.reported_total_tokens.label("reported_total_tokens"),
    ]


def _annotation_calls(run_id: str) -> Select[Any]:
    """本 run 的标注 Agent 调用（执行行直接带 run 与标注角色）"""
    task_type, call_type = _AGENT_CALL_BUCKETS["annotation"]
    return select(*_agent_call_columns(task_type, call_type)).where(
        ModelCall.execution_id.in_(_annotation_execution_ids(run_id))
    )


def _diagnosis_calls(run_id: str) -> Select[Any]:
    """本 run 的诊断 Agent 调用（执行行直接带 run 与诊断角色）"""
    task_type, call_type = _AGENT_CALL_BUCKETS["diagnosis"]
    return select(*_agent_call_columns(task_type, call_type)).where(
        ModelCall.execution_id.in_(_diagnosis_execution_ids(run_id))
    )


def _agent_calls(run_id: str) -> CompoundSelect:
    """本 run 的 Agent 模型调用（标注与诊断两类执行角色各自的直接归属）"""
    return union_all(_annotation_calls(run_id), _diagnosis_calls(run_id))


def _standalone_calls(run_id: str) -> Select[Any]:
    """本 run 的非 Agent 真实模型调用（standalone 上下文列，不伪造工作身份）"""
    return select(
        ModelCall.call_id.label("call_id"),
        ModelCall.model.label("model"),
        ModelCall.status.label("status"),
        ModelCall.standalone_task_type.label("task_type"),
        ModelCall.standalone_call_type.label("call_type"),
        ModelCall.prompt_tokens.label("prompt_tokens"),
        ModelCall.completion_tokens.label("completion_tokens"),
        ModelCall.cache_read_tokens.label("cache_read_tokens"),
        ModelCall.reasoning_tokens.label("reasoning_tokens"),
        ModelCall.accounting_source.label("accounting_source"),
        ModelCall.reported_total_tokens.label("reported_total_tokens"),
    ).where(ModelCall.standalone_run_id == run_id, ModelCall.execution_id.is_(None))


def _usage_calls(run_id: str):
    """本 run 参与计账的全部真实调用（Agent 调用 + 非 Agent 调用）"""
    return union_all(_annotation_calls(run_id), _diagnosis_calls(run_id), _standalone_calls(run_id)).subquery(
        "usage_calls"
    )


def _total_tokens_expression(calls: Any) -> Any:
    """按分项 fallback 的 total_tokens 表达式；实报总量优先"""
    return func.coalesce(
        calls.c.reported_total_tokens,
        func.coalesce(calls.c.prompt_tokens, 0) + func.coalesce(calls.c.completion_tokens, 0),
    )


def _fetch_usage_summary(session: Session, run_id: str) -> dict[str, Any]:
    """获取使用量摘要"""
    calls = _usage_calls(run_id)
    stmt = select(
        func.count().label("call_count"),
        func.sum(calls.c.prompt_tokens).label("total_prompt_tokens"),
        func.sum(func.coalesce(calls.c.completion_tokens, 0)).label("total_completion_tokens"),
        func.sum(_total_tokens_expression(calls)).label("total_tokens"),
    )
    result = session.execute(stmt).fetchone()
    if result is None:
        return {
            "call_count": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_tokens": 0,
        }
    return {
        "call_count": result.call_count or 0,
        "total_prompt_tokens": result.total_prompt_tokens or 0,
        "total_completion_tokens": result.total_completion_tokens or 0,
        "total_tokens": result.total_tokens or 0,
    }


def _fetch_usage_by_task(session: Session, run_id: str) -> dict[str, Any]:
    """按任务类型获取使用量"""
    calls = _usage_calls(run_id)
    stmt = (
        select(
            calls.c.task_type,
            func.count().label("call_count"),
            func.sum(_total_tokens_expression(calls)).label("total_tokens"),
        )
        .group_by(calls.c.task_type)
    )

    result = session.execute(stmt).fetchall()
    aggregated: dict[str, dict[str, int]] = {}
    for row in result:
        bucket = aggregated.setdefault(row.task_type, {"call_count": 0, "total_tokens": 0})
        # 列名不能用 count：mypy 会把它当成序列方法而不是 SQL 列
        bucket["call_count"] += int(row.call_count or 0)
        bucket["total_tokens"] += int(row.total_tokens or 0)
    return aggregated


def _build_call_type_key(task_type: str, call_type: str) -> str:
    """构建对外统一的调用桶 key"""
    return f"{task_type}.{call_type}"


def _fetch_usage_by_call_type(session: Session, run_id: str) -> dict[str, Any]:
    """按 task_type + call_type 获取使用量"""
    calls = _usage_calls(run_id)
    stmt = (
        select(
            calls.c.task_type,
            calls.c.call_type,
            func.count().label("call_count"),
            func.sum(_total_tokens_expression(calls)).label("total_tokens"),
        )
        .group_by(calls.c.task_type, calls.c.call_type)
    )

    result = session.execute(stmt).fetchall()
    aggregated: dict[str, dict[str, int]] = {}
    for row in result:
        key = _build_call_type_key(row.task_type, row.call_type)
        bucket = aggregated.setdefault(key, {"call_count": 0, "total_tokens": 0})
        bucket["call_count"] += int(row.call_count or 0)
        bucket["total_tokens"] += int(row.total_tokens or 0)
    return aggregated


def _fetch_usage_by_model(session: Session, run_id: str) -> dict[str, Any]:
    """按模型获取使用量"""
    calls = _usage_calls(run_id)
    stmt = (
        select(
            calls.c.model,
            func.count().label("call_count"),
            func.sum(_total_tokens_expression(calls)).label("total_tokens"),
        )
        .group_by(calls.c.model)
    )

    result = session.execute(stmt).fetchall()
    return {
        row.model: {
            "call_count": int(row.call_count or 0),
            "total_tokens": int(row.total_tokens or 0),
        }
        for row in result
    }


def _detect_token_coverage_gaps(
    session: Session,
    run_id: str,
) -> list[str]:
    """找出计账口径不完整的 Agent 调用桶

    缺口三类：尚未收口的 running 调用、没有用量分项的行、只能本地估算的行。
    """
    calls = _agent_calls(run_id).subquery("agent_calls")
    gaps: set[str] = set()
    statement = select(calls.c.task_type, calls.c.call_type).where(
        (calls.c.status == "running")
        | (calls.c.prompt_tokens.is_(None))
        | (func.coalesce(calls.c.accounting_source, "") != "reported")
    )
    for row in session.execute(statement):
        gaps.add(_build_call_type_key(row.task_type, row.call_type))
    return sorted(gaps)


def fetch_agent_turns(session: Session, run_id: str) -> list[AuditedTurn]:
    """读取本 run 的 Agent 回合视图（按 call_id 先后排序）

    model_calls 宽行的 execution_id+turn_index 决定身份与回合序，用量分项/实报/
    费用/五类计时/计时备注/四类文档都取自同一行的具名列；四个 bytes 列缺值表示
    当时没有该观察，不伪造空文档。
    """
    calls = list(
        session.execute(
            select(ModelCall)
            .where(ModelCall.execution_id.in_(run_agent_execution_ids(run_id)))
            .order_by(ModelCall.call_id)
        ).scalars()
    )
    if not calls:
        return []
    execution_ids = {str(call.execution_id) for call in calls}
    annotation_executions = set(
        session.scalars(
            select(Execution.execution_id).where(
                Execution.execution_id.in_(execution_ids), Execution.role.in_(ANNOTATION_ROLES)
            )
        )
    )
    turns: list[AuditedTurn] = []
    for call in calls:
        execution_id = str(call.execution_id)
        if call.turn_index is None:
            # 形状约束保证 Agent 调用必有执行与回合序号；缺序号说明数据异常，不静默投影
            raise RuntimeError(f"Agent 调用缺少回合序号: {call.call_id}")
        bucket = _AGENT_CALL_BUCKETS["annotation" if execution_id in annotation_executions else "diagnosis"]
        timings = _read_timings(call)
        turns.append(
            AuditedTurn(
                call_id=int(call.call_id),
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


def fetch_run_tool_calls(session: Session, run_id: str) -> list[AuditedToolCall]:
    """读取本 run 的工具调用视图（按 tool_call_id 先后排序）"""
    call_ids = [turn.call_id for turn in fetch_agent_turns(session, run_id)]
    if not call_ids:
        return []
    rows = session.execute(
        select(AgentToolCall).where(AgentToolCall.call_id.in_(call_ids)).order_by(AgentToolCall.id)
    ).scalars()
    return [
        AuditedToolCall(
            tool_call_id=int(tool_call.id),
            call_id=int(tool_call.call_id),
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
    "run_agent_execution_ids",
]
