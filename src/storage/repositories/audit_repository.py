"Agent、回合与工具调用审计的独立短事务保存"

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from src.storage.models import Agent, AgentLoop, ToolCall
from src.storage.models.base import naive_utcnow
from src.storage.records.audit_documents import encode_document, encode_text_document

_TIMING_COLUMNS = {
    "ttft": "ttft_ms",
    "first_visible": "first_visible_ms",
    "reasoning": "reasoning_ms",
    "model": "model_ms",
}


class AuditRepository:
    "只保存真实 Agent 身份和实际调用观察"

    def __init__(self, session):
        self._session = session

    def _ensure_agent(self, agent_id: str, run_id: str | None, role: str | None) -> Agent:
        row = self._session.get(Agent, agent_id)
        if row is not None:
            if (run_id is not None and row.run_id != run_id) or (role is not None and row.type != role):
                raise ValueError("Agent 身份与运行或类型不一致")
            return row
        if not agent_id or not run_id or not role:
            raise ValueError("登记 Agent 必须提供身份、运行及类型")
        row = Agent(id=agent_id, run_id=run_id, type=role, status="running")
        self._session.add(row)
        self._session.flush()
        return row

    def start_invocation(
        self, *, agent_id: str | None = None, run_id: str | None = None, role: str | None = None, **context: Any
    ) -> int:
        "在真实 Agent 开始时登记身份"
        if not agent_id:
            raise ValueError("Agent 身份不能为空")
        self._ensure_agent(agent_id, run_id, role)
        return 0

    def start_turn(
        self,
        *,
        run_id: str,
        model: str,
        agent_id: str,
        role: str | None,
        turn_index: int,
        context_summary: dict[str, Any],
        request_messages: list[dict[str, Any]],
        message_key: str | None = None,
        **context: Any,
    ) -> str:
        "在模型请求发出前保存真实回合"
        if message_key:
            existing = self._session.scalar(select(AgentLoop.id).where(AgentLoop.message_key == message_key))
            if existing is not None:
                return str(existing)
        self._ensure_agent(agent_id, run_id, role)
        row = AgentLoop(
            agent_id=agent_id,
            turn_index=turn_index,
            model=model,
            started_at=naive_utcnow(),
            message_key=message_key,
            request_messages_bytes=encode_document(request_messages),
            context_observed_bytes=encode_document(context_summary),
            timing_notes_bytes=encode_document(["provider_request_started"]),
        )
        self._session.add(row)
        self._session.flush()
        return str(row.id)

    def finish_turn(
        self,
        turn_id: str,
        *,
        raw_response: dict[str, Any],
        error: str | None,
        timing: dict[str, int | None],
        timing_notes: list[str],
        token_usage: dict[str, Any] | None,
    ) -> None:
        "保存模型实际响应、失败原因与计账观察"
        row = self._session.get(AgentLoop, turn_id)
        if row is None:
            raise ValueError(f"回合审计行不存在: {turn_id}")
        row.error = error
        row.finished_at = naive_utcnow()
        row.raw_response_bytes = encode_document(raw_response)
        row.timing_notes_bytes = encode_document(timing_notes)
        for kind, column in _TIMING_COLUMNS.items():
            value = timing.get(f"{kind}_ms")
            if value is not None:
                setattr(row, column, int(value))
        if token_usage is not None:
            self._write_usage(row, token_usage)
        self._session.flush()

    def update_turn_timings(self, turn_id: str, *, tool_wall_ms: int | None, turn_ms: int | None) -> None:
        "工具批处理完成后记录实际墙钟耗时"
        row = self._session.get(AgentLoop, turn_id)
        if row is None:
            raise ValueError(f"回合审计行不存在: {turn_id}")
        if tool_wall_ms is not None:
            row.tool_wall_ms = int(tool_wall_ms)
        row.finished_at = naive_utcnow()
        self._session.flush()

    def record_tool_call(
        self,
        *,
        turn_id: str,
        call_index: int,
        tool_name: str,
        request_args: dict[str, Any],
        raw_args: str | None = None,
        response: dict[str, Any] | None = None,
        receipt: dict[str, Any] | None = None,
        error: str | None = None,
        tool_duration_ms: int | None = None,
        message_key: str | None = None,
    ) -> None:
        "保存一次工具调用，不建立额外状态或案例交付行"
        if message_key and self._session.scalar(select(ToolCall.id).where(ToolCall.message_key == message_key)):
            return
        self._session.add(
            ToolCall(
                agentloop_id=turn_id,
                call_index=call_index,
                tool_name=tool_name,
                error=error,
                started_at=naive_utcnow(),
                tool_duration_ms=tool_duration_ms,
                message_key=message_key,
                raw_args_bytes=None if raw_args is None else encode_text_document(raw_args),
                executed_args_bytes=encode_document(request_args),
                response_observed_bytes=None if response is None else encode_document(response),
                receipt_observed_bytes=None if receipt is None else encode_document(receipt),
            )
        )
        self._session.flush()

    def finish_invocation(
        self, *, agent_id: str, status: str, run_id: str | None = None, role: str | None = None, **context: Any
    ) -> None:
        "记录真实 Agent 的运行结局"
        row = self._ensure_agent(agent_id, run_id, role)
        if status not in {"success", "error"}:
            raise ValueError("Agent 结束状态必须为 success 或 error")
        if row.status not in {"running", status}:
            raise RuntimeError("Agent 已有不同终态")
        row.status = status
        self._session.flush()

    @staticmethod
    def _write_usage(row: AgentLoop, usage: dict[str, Any]) -> None:
        "区分供应商实报与本地估算，不重复累加推理或缓存用量"
        source = str(usage.get("accounting_source") or "reported")
        row.accounting_source = source
        row.prompt_tokens = int(usage.get("prompt_tokens") or 0)
        row.completion_tokens = int(usage.get("completion_tokens") or 0)
        row.cache_read_tokens = usage.get("cache_read_tokens")
        row.reasoning_tokens = usage.get("reasoning_tokens")
        if source == "reported" and usage.get("total_tokens") is not None:
            row.reported_total_tokens = int(usage["total_tokens"])
        if usage.get("cost") is not None:
            row.cost = float(usage["cost"])
