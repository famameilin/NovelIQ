"Agent 审计记录器（Annotation 与 Diagnosis 共用）"

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select, update

from src.storage.models import AgentToolCall, Execution, ModelCall
from src.storage.models.base import naive_utcnow
from src.storage.records.audit_documents import encode_document, encode_text_document
from src.storage.repositories.queries.audit_queries import run_agent_execution_ids

_PROVIDER_REQUEST_STARTED_NOTE = "provider_request_started"
_ORPHAN_INTERRUPT_ERROR = "进程重启遗留：回合未正常收口"
_TIMING_COLUMNS: dict[str, str] = {
    "ttft": "ttft_ms",
    "first_visible": "first_visible_ms",
    "reasoning": "reasoning_ms",
    "model": "model_ms",
}


class AuditRepository:
    "用于以独立短事务持久化 Agent 审计数据"

    def __init__(self, session):
        self._session = session

    def _utcnow(self) -> datetime:
        "用于按无时区数据库列合同生成 naive UTC 审计时间"
        return naive_utcnow()

    def _commit(self, session):
        session.flush()

    def start_invocation(
        self,
        *,
        execution_id: str | None = None,
        task_type: str | None = None,
        attempt_number: int = 1,
        run_id: str | None = None,
        role: str | None = None,
        chapter_id: int | None = None,
        case_anchor: str | None = None,
        **_: Any,
    ) -> int:
        "用于在派发时登记真实执行事实（含未发出请求就失败的尝试）"
        del task_type
        if execution_id:
            session = self._session
            try:
                self._ensure_invocation(
                    session,
                    execution_id=execution_id,
                    run_id=run_id,
                    role=role,
                    chapter_id=chapter_id,
                    case_anchor=case_anchor,
                    attempt_number=attempt_number,
                )
            except Exception:
                raise
            self._commit(session)
        return 0

    def start_turn(
        self,
        *,
        run_id: str,
        task_type: str,
        call_type: str,
        model: str,
        execution_id: str,
        attempt_number: int,
        chapter_id: int | None,
        role: str | None,
        turn_index: int,
        context_summary: dict[str, Any],
        request_messages: list[dict[str, Any]],
        case_anchor: str | None = None,
        message_key: str | None = None,
        invocation_id: int | None = None,
    ) -> str:
        "用于在物理 Provider 请求发出前创建独立运行中模型调用"
        del task_type, call_type, invocation_id
        session = self._session
        try:
            existing = self._message_key_call(session, message_key)
            if existing is not None:
                return existing
            self._ensure_invocation(
                session,
                execution_id=execution_id,
                run_id=run_id,
                role=role,
                chapter_id=chapter_id,
                case_anchor=case_anchor,
                attempt_number=attempt_number,
            )
            call = ModelCall(
                model=model,
                status="running",
                error=None,
                started_at=self._utcnow(),
                finished_at=None,
                message_key=message_key,
                execution_id=execution_id,
                turn_index=int(turn_index),
                request_messages_bytes=encode_document(request_messages),
                context_observed_bytes=encode_document(context_summary),
                timing_notes_bytes=encode_document([_PROVIDER_REQUEST_STARTED_NOTE]),
            )
            session.add(call)
            session.flush()
            call_id = str(call.call_id)
        except Exception:
            raise
        self._commit(session)
        return call_id

    def finish_turn(
        self,
        turn_id: str,
        *,
        raw_response: dict[str, Any],
        status: str,
        error: str | None,
        timing: dict[str, int | None],
        timing_notes: list[str],
        token_usage: dict[str, Any] | None,
    ) -> None:
        "用于按物理 Provider 请求结束状态补齐响应计时错误与 token 计账"
        now = self._utcnow()
        session = self._session
        try:
            call = session.get(ModelCall, turn_id)
            if call is None:
                raise RuntimeError(f"model call 审计行不存在: {turn_id}")
            if call.status != "running":
                if call.status == status and (call.error or None) == (error or None):
                    return
                raise RuntimeError(f"model call 已结束，不能按不同结果重复收口: {turn_id}")
            call.status = status
            call.error = error
            call.finished_at = now
            call.raw_response_bytes = encode_document(raw_response)
            call.timing_notes_bytes = encode_document([str(note) for note in timing_notes])
            for timing_kind, column in _TIMING_COLUMNS.items():
                elapsed_ms = timing.get(f"{timing_kind}_ms")
                if elapsed_ms is not None:
                    setattr(call, column, int(elapsed_ms))
            if token_usage is not None:
                self._write_usage(call, token_usage)
        except Exception:
            raise
        self._commit(session)

    def update_turn_timings(self, turn_id: str, *, tool_wall_ms: int | None, turn_ms: int | None) -> None:
        "用于在工具批处理结束后补写工具墙钟与本回合总耗时"
        del turn_ms
        session = self._session
        try:
            call = session.get(ModelCall, turn_id)
            if call is None:
                raise RuntimeError(f"model call 审计行不存在: {turn_id}")
            if tool_wall_ms is not None:
                call.tool_wall_ms = int(tool_wall_ms)
            call.finished_at = self._utcnow()
        except Exception:
            raise
        self._commit(session)

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
        status: str = "success",
        error: str | None = None,
        tool_duration_ms: int | None = None,
        message_key: str | None = None,
    ) -> None:
        "用于在独立短事务中写入单次工具调用审计（含原始参数片段）"
        session = self._session
        try:
            if self._tool_message_key_call(session, message_key) is not None:
                return
            row = AgentToolCall(
                call_id=turn_id,
                tool_name=tool_name,
                call_index=int(call_index),
                status=status,
                error=error,
                started_at=self._utcnow(),
                tool_duration_ms=None if tool_duration_ms is None else int(tool_duration_ms),
                message_key=message_key,
                raw_args_bytes=None if raw_args is None else encode_text_document(raw_args),
                executed_args_bytes=encode_document(request_args),
                response_observed_bytes=None if response is None else encode_document(response),
                receipt_observed_bytes=None if receipt is None else encode_document(receipt),
            )
            session.add(row)
        except Exception:
            raise
        self._commit(session)

    def finish_invocation(
        self,
        *,
        execution_id: str,
        status: str,
        task_type: str | None = None,
        attempt_number: int = 1,
        run_id: str | None = None,
        role: str | None = None,
        chapter_id: int | None = None,
        case_anchor: str | None = None,
        final_error: str | None = None,
        message_key: str | None = None,
        **_: Any,
    ) -> None:
        "用于把执行收口为真实终态"
        del message_key, task_type
        now = self._utcnow()
        session = self._session
        try:
            execution = session.get(Execution, execution_id)
            if execution is None:
                self._ensure_invocation(
                    session,
                    execution_id=execution_id,
                    run_id=run_id,
                    role=role,
                    chapter_id=chapter_id,
                    case_anchor=case_anchor,
                    attempt_number=attempt_number,
                    status=status,
                    error=final_error,
                    started_at=now,
                    finished_at=now,
                )
            elif execution.status is None:
                raise RuntimeError(f"整轮 session 不能按尝试终态收口: {execution_id}")
            elif execution.status != "running":
                if execution.status == status and (execution.error or None) == (final_error or None):
                    return
                raise RuntimeError(f"execution 已结束，不能按不同结果重复收口: {execution_id}")
            else:
                execution.status = status
                execution.error = final_error
                execution.finished_at = now
        except Exception:
            raise
        self._commit(session)

    def close_orphaned_turns(self, run_id: str) -> int:
        "用于分析环境初始化时收口本 run 遗留的 running 执行与调用"
        execution_ids = run_agent_execution_ids(run_id)
        now = self._utcnow()
        session = self._session
        try:
            calls = session.execute(
                update(ModelCall)
                .where(
                    ModelCall.execution_id.in_(execution_ids),
                    ModelCall.status == "running",
                    ModelCall.finished_at.is_(None),
                )
                .values(status="interrupted", error=_ORPHAN_INTERRUPT_ERROR, finished_at=now)
            )
            executions = session.execute(
                update(Execution)
                .where(
                    Execution.execution_id.in_(execution_ids),
                    Execution.status == "running",
                    Execution.finished_at.is_(None),
                )
                .values(status="interrupted", error=_ORPHAN_INTERRUPT_ERROR, finished_at=now)
            )
            session.flush()
            return int(calls.rowcount or 0) + int(executions.rowcount or 0)
        finally:
            pass

    def _ensure_invocation(
        self,
        session: Any,
        *,
        execution_id: str,
        run_id: str | None,
        role: str | None,
        chapter_id: int | None = None,
        case_anchor: str | None = None,
        attempt_number: int,
        status: str = "running",
        error: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> Execution:
        "确保真实 invocation 执行行存在；归属缺失时保留合同报错，不伪造归属"
        existing = session.get(Execution, execution_id)
        if existing is not None:
            return existing
        if not run_id or not role:
            raise RuntimeError(f"执行归属未提供（run/角色必填），不能登记真实 invocation: {execution_id!r}")
        execution = Execution(
            execution_id=execution_id,
            run_id=run_id,
            role=role,
            chapter_id=chapter_id,
            case_anchor=case_anchor,
            attempt_number=int(attempt_number or 1),
            started_at=started_at if started_at is not None else self._utcnow(),
            finished_at=finished_at,
            status=status,
            error=error,
        )
        session.add(execution)
        session.flush()
        return execution

    @staticmethod
    def _message_key_call(session: Any, message_key: str | None) -> str | None:
        "按审计消息键找回已落库的模型调用（重放幂等）"
        if not message_key:
            return None
        call_id = session.execute(
            select(ModelCall.call_id).where(ModelCall.message_key == message_key)
        ).scalar_one_or_none()
        return str(call_id) if call_id is not None else None

    @staticmethod
    def _tool_message_key_call(session: Any, message_key: str | None) -> str | None:
        "按审计消息键找回已落库的工具调用（重放幂等）"
        if not message_key:
            return None
        tool_call_id = session.execute(
            select(AgentToolCall.id).where(AgentToolCall.message_key == message_key)
        ).scalar_one_or_none()
        return str(tool_call_id) if tool_call_id is not None else None

    @staticmethod
    def _write_usage(call: ModelCall, token_usage: dict[str, Any]) -> None:
        "用量分项与供应商实报总量分开：程序 fallback 不伪装实报"
        accounting_source = str(token_usage.get("accounting_source") or "reported")
        call.prompt_tokens = int(token_usage.get("prompt_tokens") or 0)
        call.completion_tokens = int(token_usage.get("completion_tokens") or 0)
        call.cache_read_tokens = token_usage.get("cache_read_tokens")
        call.reasoning_tokens = token_usage.get("reasoning_tokens")
        call.accounting_source = accounting_source
        if accounting_source == "reported":
            total = token_usage.get("total_tokens")
            if total is not None:
                call.reported_total_tokens = int(total)
        cost = token_usage.get("cost")
        if cost is not None:
            call.cost = float(cost)


__all__ = ["AuditRepository"]
