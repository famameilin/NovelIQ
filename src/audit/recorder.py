"""
Agent 审计记录器（Annotation 与 Diagnosis 共用）

2026-10-06 表合并：invocation 不再单独落行，其上下文由 AuditModule 保存在内存并随
start_turn 注入回合行；token 计账列内联在 model_turns 行上。
每次审计写入使用独立短事务即时提交，不随候选状态或最终标注事务回滚；
审计写入失败直接抛出异常终止 Agent，不静默忽略。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import update

from src.storage.models.agent_audit import AgentToolCall, ModelTurn

_ATTEMPT_ERROR_TURN_INDEX = 0


class AgentAuditRecorder:
    """2026-08-10 用于以独立短事务持久化 Agent 审计数据"""

    def __init__(self, session_factory: Callable[[], Any], *, owns_transaction: bool = True) -> None:
        """2026-08-10 用于绑定每次审计写入的独立 Session 工厂"""
        self._session_factory = session_factory
        self._owns_transaction = owns_transaction

    def _utcnow(self) -> datetime:
        """2026-08-30 用于按无时区数据库列合同生成 naive UTC 审计时间"""
        return datetime.now(UTC).replace(tzinfo=None)

    def _commit(self, session: Any) -> None:
        """2026-08-10 用于提交短事务并在任何失败时关闭连接且不吞错"""
        if not self._owns_transaction:
            session.flush()
            return
        try:
            session.commit()
        finally:
            session.close()

    def start_invocation(self, **_: Any) -> int:
        """invocation 不再单独落行：上下文随每条审计调用流动并落到回合行。

        保留方法占位使总线适配器与直连注入共用同一调用面；返回值只是本地句柄。
        """
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
        work_id: str | None,
        role: str | None,
        turn_index: int,
        context_summary: dict[str, Any],
        request_messages: list[dict[str, Any]],
        message_key: str | None = None,
        invocation_id: int | None = None,
    ) -> int:
        """2026-08-30 用于在物理 Provider 请求发出前创建独立运行中审计行

        invocation_id 只是观察器经总线适配器传递的本地句柄，行数据以显式上下文为准。
        """
        now = self._utcnow()
        session = self._session_factory()
        turn = ModelTurn(
            row_kind="agent_turn",
            run_id=run_id,
            task_type=task_type,
            call_type=call_type,
            model=model,
            execution_id=execution_id,
            attempt_number=attempt_number,
            chapter_id=chapter_id,
            work_id=work_id,
            role=role,
            turn_index=turn_index,
            status="running",
            error=None,
            raw_response={},
            context_summary=context_summary,
            request_messages=request_messages,
            timing_notes=["provider_request_started"],
            started_at=now,
            finished_at=None,
            message_key=message_key,
        )
        session.add(turn)
        session.flush()
        turn_id = int(turn.id)
        self._commit(session)
        return turn_id

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
        """2026-08-30 用于按物理 Provider 请求结束状态补齐响应计时错误与 token 计账"""
        now = self._utcnow()
        session = self._session_factory()
        turn = session.get(ModelTurn, turn_id)
        if turn is None:
            session.close()
            raise RuntimeError(f"model turn 审计行不存在: {turn_id}")
        if turn.status != "running":
            # 审计消息跨模块重放时同一结果会重复收口，按幂等处理；不同结果才是真重复收口
            if turn.status == status and (turn.error or None) == (error or None):
                session.close()
                return
            session.close()
            raise RuntimeError(f"model turn 已结束，不能按不同结果重复收口: {turn_id}")
        turn.status = status
        turn.error = error
        turn.raw_response = raw_response
        turn.timing_notes = timing_notes
        turn.ttft_ms = timing.get("ttft_ms")
        turn.first_visible_ms = timing.get("first_visible_ms")
        turn.reasoning_ms = timing.get("reasoning_ms")
        turn.model_ms = timing.get("model_ms")
        turn.turn_ms = timing.get("model_ms")
        turn.finished_at = now
        if token_usage is not None:
            turn.prompt_tokens = int(token_usage.get("prompt_tokens") or 0)
            turn.completion_tokens = int(token_usage.get("completion_tokens") or 0)
            turn.total_tokens = int(token_usage.get("total_tokens") or 0)
            turn.cache_read_tokens = token_usage.get("cache_read_tokens")
            turn.reasoning_tokens = token_usage.get("reasoning_tokens")
            turn.cost = token_usage.get("cost")
            turn.accounting_source = str(token_usage.get("accounting_source") or "reported")
        self._commit(session)

    def update_turn_timings(
        self,
        turn_id: int,
        *,
        tool_wall_ms: int | None,
        turn_ms: int | None,
    ) -> None:
        """2026-08-10 用于在工具批处理结束后补写工具墙钟与本回合总耗时"""
        session = self._session_factory()
        row = session.get(ModelTurn, turn_id)
        if row is None:
            session.close()
            raise RuntimeError(f"model turn 审计行不存在: {turn_id}")
        row.tool_wall_ms = tool_wall_ms
        row.turn_ms = turn_ms
        # 2026-08-13 P2-10 回合在工具批处理结束后才算真正结束：同步更新
        # finished_at，避免 finished_at 恒等于插入时刻（模型输出结束时间）
        row.finished_at = self._utcnow()
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
        """2026-08-11 用于在独立短事务中写入单次工具调用审计（含原始参数片段）"""
        session = self._session_factory()
        session.add(
            AgentToolCall(
                turn_id=turn_id,
                tool_name=tool_name,
                call_index=call_index,
                request_args=request_args,
                raw_args=raw_args,
                response=response,
                receipt=receipt,
                status=status,
                error=error,
                tool_duration_ms=tool_duration_ms,
                started_at=self._utcnow(),
                message_key=message_key,
            )
        )
        self._commit(session)

    def finish_invocation(
        self,
        *,
        run_id: str,
        task_type: str,
        call_type: str,
        model: str,
        execution_id: str,
        attempt_number: int,
        chapter_id: int | None,
        work_id: str | None,
        role: str | None,
        status: str,
        final_error: str | None = None,
        message_key: str | None = None,
    ) -> None:
        """2026-10-06 用于把失败尝试收口为派发失败行（turn_index=0）

        成功尝试的全部事实已在回合行上，不再落额外行；失败尝试（含未发出任何
        模型请求的派发失败）以 attempt_error 行保存执行上下文与最终错误。
        """
        if status != "error":
            return
        now = self._utcnow()
        session = self._session_factory()
        session.add(
            ModelTurn(
                row_kind="attempt_error",
                run_id=run_id,
                task_type=task_type,
                call_type=call_type,
                model=model,
                execution_id=execution_id,
                attempt_number=attempt_number,
                chapter_id=chapter_id,
                work_id=work_id,
                role=role,
                turn_index=_ATTEMPT_ERROR_TURN_INDEX,
                status="error",
                error=final_error,
                started_at=now,
                finished_at=now,
                message_key=message_key,
            )
        )
        self._commit(session)

    def close_orphaned_turns(self, run_id: str) -> int:
        """2026-10-03 用于分析环境初始化时收口本 run 遗留的 running 回合行

        进程被杀/重启时正在执行的回合没机会走 finish_turn，永远停在
        status='running' 且 finished_at 为空（run 08f9ba42 实证 12 条僵尸行污染
        错误率统计）。每次创建/恢复分析任务时统一收口为 interrupted——审计是事实
        记录，只补状态不删除。
        """
        session = self._session_factory()
        try:
            result = session.execute(
                update(ModelTurn)
                .where(
                    ModelTurn.run_id == run_id,
                    ModelTurn.row_kind == "agent_turn",
                    ModelTurn.status == "running",
                    ModelTurn.finished_at.is_(None),
                )
                .values(
                    status="interrupted",
                    error="进程重启遗留：回合未正常收口",
                    finished_at=self._utcnow(),
                )
            )
            session.commit()
            return int(result.rowcount or 0)
        finally:
            session.close()


__all__ = ["AgentAuditRecorder"]
