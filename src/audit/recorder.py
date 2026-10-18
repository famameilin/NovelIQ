"""
Agent 审计记录器（Annotation 与 Diagnosis 共用）

审计事实全部落到三张宽表：
- executions 保存每个真实 invocation 的终态并直接携带归属（run、执行角色、
  标注章或案例锚）；没有模型请求的派发失败只写执行终态，不伪造 turn=0
- model_calls 保存每条真实模型请求：Agent 上下文（execution_id+turn_index）或
  standalone 上下文恰一；用量分项、供应商实报总量、费用、五类计时与四类通信/
  观察文档都是本表明确列，审计消息键直接落在可空唯一列上
- agent_tool_calls 保存每次真实外层工具调用：原始参数与实际执行参数分开，
  耗时与四类观察文档同列保存
每次审计写入使用独立短事务即时提交，不随候选状态或最终标注事务回滚；
审计写入失败直接抛出异常终止 Agent，不静默忽略。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import select, update

from src.audit.documents import encode_document, encode_text_document
from src.audit.queries import run_agent_execution_ids
from src.storage.models import AgentToolCall, Execution, ModelCall
from src.storage.models.base import naive_utcnow

_PROVIDER_REQUEST_STARTED_NOTE = "provider_request_started"
_ORPHAN_UNPERSISTED_ERROR = "进程重启前未落库"

#: 审计计时类别 → model_calls 的五类计时列（turn_ms 是 model+tool_wall 的读取投影）
_TIMING_COLUMNS: dict[str, str] = {
    "ttft": "ttft_ms",
    "first_visible": "first_visible_ms",
    "reasoning": "reasoning_ms",
    "model": "model_ms",
}


class AgentAuditRecorder:
    """以独立短事务持久化 Agent 审计数据"""

    def __init__(self, session_factory: Callable[[], Any], *, owns_transaction: bool = True) -> None:
        """绑定每次审计写入的独立 Session 工厂"""
        self._session_factory = session_factory
        self._owns_transaction = owns_transaction

    def _utcnow(self) -> datetime:
        """按无时区数据库列合同生成 naive UTC 审计时间"""
        return naive_utcnow()

    def _commit(self, session: Any) -> None:
        """提交短事务并在任何失败时关闭连接且不吞错"""
        if not self._owns_transaction:
            session.flush()
            return
        try:
            session.commit()
        finally:
            session.close()

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
        """在派发时登记真实执行事实（含未发出请求就失败的尝试）

        invocation 必须直接给出归属（run 与执行角色，标注角色再带章、案例角色
        带案例锚）；归属缺失即合同违约，直接报错。返回值仍是观察器使用的本地
        句柄（执行身份以 execution_id 为准）。
        """
        del task_type
        if execution_id:
            session = self._session_factory()
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
                session.close()
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
    ) -> int:
        """在物理 Provider 请求发出前创建独立运行中模型调用

        run/章节/角色只用于在缺登记时补齐执行归属；调用行（身份、请求消息、
        审计上下文与起始计时备注）全部落在 model_calls 宽行上，返回 call_id
        作为后续收口句柄。
        """
        del task_type, call_type, invocation_id
        session = self._session_factory()
        try:
            existing = self._message_key_call(session, message_key)
            if existing is not None:
                session.close()
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
            call_id = int(call.call_id)
        except Exception:
            session.close()
            raise
        self._commit(session)
        return call_id

    def finish_turn(
        self,
        turn_id: int,
        *,
        raw_response: dict[str, Any],
        status: str,
        error: str | None,
        timing: dict[str, int | None],
        timing_notes: list[str],
        token_usage: dict[str, Any] | None,
    ) -> None:
        """按物理 Provider 请求结束状态补齐响应计时错误与 token 计账"""
        now = self._utcnow()
        session = self._session_factory()
        try:
            call = session.get(ModelCall, turn_id)
            if call is None:
                raise RuntimeError(f"model call 审计行不存在: {turn_id}")
            if call.status != "running":
                # 审计消息跨模块重放时同一结果会重复收口，按幂等处理；不同结果才是真重复收口
                if call.status == status and (call.error or None) == (error or None):
                    session.close()
                    return
                session.close()
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
            session.close()
            raise
        self._commit(session)

    def update_turn_timings(
        self,
        turn_id: int,
        *,
        tool_wall_ms: int | None,
        turn_ms: int | None,
    ) -> None:
        """在工具批处理结束后补写工具墙钟与本回合总耗时

        turn_ms 是按现有 model_ms + tool_wall_ms 规则的重放投影（读取时计算），
        这里只登记实际测得的 tool_wall_ms；调用的 finished_at 随工具批处理结束更新。
        """
        del turn_ms
        session = self._session_factory()
        try:
            call = session.get(ModelCall, turn_id)
            if call is None:
                raise RuntimeError(f"model call 审计行不存在: {turn_id}")
            if tool_wall_ms is not None:
                call.tool_wall_ms = int(tool_wall_ms)
            # 回合在工具批处理结束后才算真正结束：同步更新 finished_at
            call.finished_at = self._utcnow()
        except Exception:
            session.close()
            raise
        self._commit(session)

    def record_tool_call(
        self,
        *,
        turn_id: int,
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
        """在独立短事务中写入单次工具调用审计（含原始参数片段）

        turn_id 即真实模型调用的 call_id；实际执行参数与原始参数字符串分开保存，
        观察文档与耗时同列落在 agent_tool_calls 宽行上。
        """
        session = self._session_factory()
        try:
            if self._tool_message_key_call(session, message_key) is not None:
                session.close()
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
            session.close()
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
        """把执行收口为真实终态

        没有发出任何模型请求的派发失败也只写执行记录（不伪造第 0 个模型回合）；
        成功尝试同样登记成功终态，模型请求事实仍只在其调用行上。
        重放幂等由终态相等承担：同状态同错误重复收口不报错，不同结果报错。
        """
        del message_key, task_type
        now = self._utcnow()
        session = self._session_factory()
        try:
            execution = session.get(Execution, execution_id)
            if execution is None:
                # 未登记执行的收口请求：按真实终态补登记执行事实（归属必须已给出）
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
                session.close()
                raise RuntimeError(f"整轮 session 不能按尝试终态收口: {execution_id}")
            elif execution.status != "running":
                if execution.status == status and (execution.error or None) == (final_error or None):
                    session.close()
                    return
                session.close()
                raise RuntimeError(f"execution 已结束，不能按不同结果重复收口: {execution_id}")
            else:
                execution.status = status
                execution.error = final_error
                execution.finished_at = now
        except Exception:
            session.close()
            raise
        self._commit(session)

    def close_orphaned_turns(self, run_id: str) -> int:
        """分析环境初始化时按落库事实收口本 run 遗留的 running 执行与调用

        运行已有正式诊断报告（诊断产物落库）时，其残留诊断会话行按成功收口；
        其余未落库的回合按未落库收口。审计是事实记录，只补状态不删除。
        返回值是本次收口的调用行与执行行总数。
        """
        execution_ids = run_agent_execution_ids(run_id)
        now = self._utcnow()
        session = self._session_factory()
        try:
            settled = 0
            if self._run_has_published_diagnosis(session, run_id):
                from src.storage.models.work import DIAGNOSIS_ROLES

                completed = session.execute(
                    update(Execution)
                    .where(
                        Execution.execution_id.in_(execution_ids),
                        Execution.role.in_(DIAGNOSIS_ROLES),
                        Execution.status == "running",
                        Execution.finished_at.is_(None),
                    )
                    .values(status="success", finished_at=now)
                )
                settled = int(completed.rowcount or 0)
            calls = session.execute(
                update(ModelCall)
                .where(
                    ModelCall.execution_id.in_(execution_ids),
                    ModelCall.status == "running",
                    ModelCall.finished_at.is_(None),
                )
                .values(status="error", error=_ORPHAN_UNPERSISTED_ERROR, finished_at=now)
            )
            executions = session.execute(
                update(Execution)
                .where(
                    Execution.execution_id.in_(execution_ids),
                    Execution.status == "running",
                    Execution.finished_at.is_(None),
                )
                .values(status="error", error=_ORPHAN_UNPERSISTED_ERROR, finished_at=now)
            )
            session.commit()
            return settled + int(calls.rowcount or 0) + int(executions.rowcount or 0)
        finally:
            session.close()

    @staticmethod
    def _run_has_published_diagnosis(session: Any, run_id: str) -> bool:
        """本 run 的诊断产物落库事实：正式诊断报告存在"""
        from src.storage.models import DiagnosisReport

        return session.scalar(
            select(DiagnosisReport.report_id)
            .join(Execution, Execution.execution_id == DiagnosisReport.session_id)
            .where(Execution.session_run_id == run_id)
            .limit(1)
        ) is not None

    # ------------------------------------------------------------------
    # 执行身份：真实 invocation（直接携带归属）
    # ------------------------------------------------------------------

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
        """确保真实 invocation 执行行存在；归属缺失时保留合同报错，不伪造归属"""
        existing = session.get(Execution, execution_id)
        if existing is not None:
            return existing
        if not run_id or not role:
            raise RuntimeError(
                f"执行归属未提供（run/角色必填），不能登记真实 invocation: {execution_id!r}"
            )
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

    # ------------------------------------------------------------------
    # 宽表写入辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _message_key_call(session: Any, message_key: str | None) -> int | None:
        """按审计消息键找回已落库的模型调用（重放幂等）"""
        if not message_key:
            return None
        call_id = session.execute(
            select(ModelCall.call_id).where(ModelCall.message_key == message_key)
        ).scalar_one_or_none()
        return int(call_id) if call_id is not None else None

    @staticmethod
    def _tool_message_key_call(session: Any, message_key: str | None) -> int | None:
        """按审计消息键找回已落库的工具调用（重放幂等）"""
        if not message_key:
            return None
        tool_call_id = session.execute(
            select(AgentToolCall.id).where(AgentToolCall.message_key == message_key)
        ).scalar_one_or_none()
        return int(tool_call_id) if tool_call_id is not None else None

    @staticmethod
    def _write_usage(call: ModelCall, token_usage: dict[str, Any]) -> None:
        """用量分项与供应商实报总量分开：程序 fallback 不伪装实报"""
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


__all__ = ["AgentAuditRecorder"]
