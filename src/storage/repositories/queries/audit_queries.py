"从 src/audit/queries.py 分离的具名物理读取"

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import CompoundSelect, Select, func, literal, select, union_all

from src.storage.models import AgentToolCall, Execution, ModelCall
from src.storage.models.work import ANNOTATION_ROLES, DIAGNOSIS_ROLES

_AGENT_CALL_BUCKETS: dict[str, tuple[str, str]] = {
    "annotation": ("annotation", "agent"),
    "diagnosis": ("diagnosis", "diagnosis"),
}


def _annotation_execution_ids(run_id: str) -> Select[Any]:
    "本 run 章内标注执行的 execution_id 选择器（执行行直接带 run 与标注角色）"
    return select(Execution.execution_id).where(Execution.run_id == run_id, Execution.role.in_(ANNOTATION_ROLES))


def _diagnosis_execution_ids(run_id: str) -> Select[Any]:
    "本 run 诊断执行（案例/报告角色）的 execution_id 选择器（执行行直接带 run）"
    return select(Execution.execution_id).where(Execution.run_id == run_id, Execution.role.in_(DIAGNOSIS_ROLES))


def run_agent_execution_ids(run_id: str) -> Select[tuple[str]]:
    "本 run 内 Agent 执行的 execution_id 选择器（两类执行归属的直接并集）"
    return cast("Select[tuple[str]]", _annotation_execution_ids(run_id).union(_diagnosis_execution_ids(run_id)))


def _annotation_calls(run_id: str) -> Select[Any]:
    "本 run 的标注 Agent 调用（执行行直接带 run 与标注角色）"
    task_type, call_type = _AGENT_CALL_BUCKETS["annotation"]
    return select(*_agent_call_columns(task_type, call_type)).where(
        ModelCall.execution_id.in_(_annotation_execution_ids(run_id))
    )


def _diagnosis_calls(run_id: str) -> Select[Any]:
    "本 run 的诊断 Agent 调用（执行行直接带 run 与诊断角色）"
    task_type, call_type = _AGENT_CALL_BUCKETS["diagnosis"]
    return select(*_agent_call_columns(task_type, call_type)).where(
        ModelCall.execution_id.in_(_diagnosis_execution_ids(run_id))
    )


def _agent_calls(run_id: str) -> CompoundSelect:
    "本 run 的 Agent 模型调用（标注与诊断两类执行角色各自的直接归属）"
    return union_all(_annotation_calls(run_id), _diagnosis_calls(run_id))


def _standalone_calls(run_id: str) -> Select[Any]:
    "本 run 的非 Agent 真实模型调用（standalone 上下文列，不伪造工作身份）"
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


def _agent_call_columns(task_type: str, call_type: str) -> list[Any]:
    "Agent 调用的统一列面：调用身份、计账桶与用量/实报投影来源"
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


def audit_queries_fetch_token_usage_stats_1(_session, run_id):
    calls = _usage_calls(run_id)
    return _session.execute(select(calls.c.accounting_source).where(calls.c.accounting_source.is_not(None))).scalars()


def audit_queries_detect_token_coverage_gaps_1(_session, run_id):
    calls = _agent_calls(run_id).subquery("agent_calls")
    statement = select(calls.c.task_type, calls.c.call_type).where(
        (calls.c.status == "running")
        | calls.c.prompt_tokens.is_(None)
        | (func.coalesce(calls.c.accounting_source, "") != "reported")
    )
    return _session.execute(statement)


def audit_queries_fetch_agent_turns_1(_session, execution_ids):
    return _session.scalars(
        select(Execution.execution_id).where(
            Execution.execution_id.in_(execution_ids), Execution.role.in_(ANNOTATION_ROLES)
        )
    )


def audit_queries_fetch_agent_turns_2(_session, run_id):
    return _session.execute(
        select(ModelCall).where(ModelCall.execution_id.in_(run_agent_execution_ids(run_id))).order_by(ModelCall.call_id)
    ).scalars()


def audit_queries_fetch_run_tool_calls_1(_session, call_ids):
    return _session.execute(
        select(AgentToolCall).where(AgentToolCall.call_id.in_(call_ids)).order_by(AgentToolCall.id)
    ).scalars()


def _usage_calls(run_id: str):
    "本 run 参与计账的全部真实调用（Agent 调用 + 非 Agent 调用）"
    return union_all(_annotation_calls(run_id), _diagnosis_calls(run_id), _standalone_calls(run_id)).subquery(
        "usage_calls"
    )


def _total_tokens_expression(calls: Any) -> Any:
    "按分项 fallback 的 total_tokens 表达式；实报总量优先"
    return func.coalesce(
        calls.c.reported_total_tokens,
        func.coalesce(calls.c.prompt_tokens, 0) + func.coalesce(calls.c.completion_tokens, 0),
    )


def audit_queries_fetch_usage_summary(_session, run_id):
    calls = _usage_calls(run_id)
    stmt = select(
        func.count().label("call_count"),
        func.sum(calls.c.prompt_tokens).label("total_prompt_tokens"),
        func.sum(func.coalesce(calls.c.completion_tokens, 0)).label("total_completion_tokens"),
        func.sum(_total_tokens_expression(calls)).label("total_tokens"),
    )
    return _session.execute(stmt).first()


def audit_queries_fetch_usage_by_task(_session, run_id):
    calls = _usage_calls(run_id)
    stmt = select(
        calls.c.task_type,
        func.count().label("call_count"),
        func.sum(_total_tokens_expression(calls)).label("total_tokens"),
    ).group_by(calls.c.task_type)
    return _session.execute(stmt).all()


def audit_queries_fetch_usage_by_call_type(_session, run_id):
    calls = _usage_calls(run_id)
    stmt = select(
        calls.c.task_type,
        calls.c.call_type,
        func.count().label("call_count"),
        func.sum(_total_tokens_expression(calls)).label("total_tokens"),
    ).group_by(calls.c.task_type, calls.c.call_type)
    return _session.execute(stmt).all()


def audit_queries_fetch_usage_by_model(_session, run_id):
    calls = _usage_calls(run_id)
    stmt = select(
        calls.c.model, func.count().label("call_count"), func.sum(_total_tokens_expression(calls)).label("total_tokens")
    ).group_by(calls.c.model)
    return _session.execute(stmt).all()
