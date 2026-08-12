"""
Agent 审计记录器（Annotation 与 Diagnosis 共用）

说明: 每次审计写入使用独立短事务即时提交，不随候选状态或最终标注事务回滚；
审计写入失败直接抛出异常终止 Agent，不静默忽略。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from src.storage.models.agent_audit import AgentInvocation, AgentToolCall, AgentTurn
from src.storage.models.rag import TokenUsage


class AgentAuditRecorder:
    """2026-08-10 用于以独立短事务持久化 Agent 审计数据"""

    def __init__(self, session_factory: Callable[[], Any]) -> None:
        """2026-08-10 用于绑定每次审计写入的独立 Session 工厂"""
        self._session_factory = session_factory

    def _utcnow(self) -> datetime:
        """2026-08-10 用于生成 UTC aware 审计定位时间"""
        return datetime.now(UTC)

    def _commit(self, session: Any) -> None:
        """2026-08-10 用于提交短事务并在任何失败时关闭连接且不吞错"""
        try:
            session.commit()
        finally:
            session.close()

    def start_invocation(
        self,
        *,
        run_id: str,
        task_type: str,
        attempt_number: int,
        model_name: str | None,
        model_provider: str | None,
        chapter_id: int | None = None,
    ) -> int:
        """2026-08-10 用于开启一次 Annotation/Diagnosis 尝试审计并返回 invocation_id"""
        session = self._session_factory()
        row = AgentInvocation(
            run_id=run_id,
            task_type=task_type,
            chapter_id=chapter_id,
            attempt_number=attempt_number,
            model_name=model_name,
            model_provider=model_provider,
            status="running",
            final_error=None,
            started_at=self._utcnow(),
            finished_at=None,
        )
        session.add(row)
        session.flush()
        invocation_id = int(row.id)
        self._commit(session)
        return invocation_id

    def finish_invocation(
        self,
        invocation_id: int,
        *,
        status: str,
        final_error: str | None = None,
    ) -> None:
        """2026-08-10 用于收口一次尝试审计的成功或失败状态"""
        session = self._session_factory()
        row = session.get(AgentInvocation, invocation_id)
        if row is None:
            session.close()
            raise RuntimeError(f"agent invocation 审计行不存在: {invocation_id}")
        row.status = status
        row.final_error = final_error
        row.finished_at = self._utcnow()
        self._commit(session)

    def record_turn(
        self,
        *,
        invocation_id: int,
        turn_index: int,
        context_summary: dict[str, Any],
        raw_response: dict[str, Any],
        status: str = "success",
        error: str | None = None,
        timing: dict[str, int | None] | None = None,
        timing_notes: list[str] | None = None,
        request_messages: list[dict[str, Any]] | None = None,
        token_usage: Mapping[str, Any] | None = None,
        run_id: str,
        novel_id: str,
        task_type: str,
        call_type: str,
        model: str,
    ) -> int:
        """2026-08-10 用于在独立短事务中写入模型回合与一对一 Token 行并返回 turn_id"""
        now = self._utcnow()
        timing = timing or {}
        session = self._session_factory()
        turn = AgentTurn(
            invocation_id=invocation_id,
            turn_index=turn_index,
            status=status,
            error=error,
            raw_response=raw_response,
            context_summary=context_summary,
            request_messages=request_messages or [],
            timing_notes=timing_notes or [],
            ttft_ms=timing.get("ttft_ms"),
            first_visible_ms=timing.get("first_visible_ms"),
            reasoning_ms=timing.get("reasoning_ms"),
            model_ms=timing.get("model_ms"),
            tool_wall_ms=timing.get("tool_wall_ms"),
            turn_ms=timing.get("turn_ms"),
            started_at=now,
            finished_at=now,
        )
        session.add(turn)
        session.flush()
        turn_id = int(turn.id)
        if token_usage is not None:
            session.add(
                TokenUsage(
                    novel_id=novel_id,
                    chunk_id=None,
                    task_type=task_type,
                    call_type=call_type,
                    model=model,
                    prompt_tokens=int(token_usage.get("prompt_tokens") or 0),
                    completion_tokens=int(token_usage.get("completion_tokens") or 0),
                    total_tokens=int(token_usage.get("total_tokens") or 0),
                    cache_read_tokens=token_usage.get("cache_read_tokens"),
                    reasoning_tokens=token_usage.get("reasoning_tokens"),
                    cost=token_usage.get("cost"),
                    accounting_source=str(token_usage.get("accounting_source") or "reported"),
                    created_at=now.isoformat(),
                    run_id=run_id,
                    agent_turn_id=turn_id,
                )
            )
        self._commit(session)
        return turn_id

    def update_turn_timings(
        self,
        turn_id: int,
        *,
        tool_wall_ms: int | None,
        turn_ms: int | None,
    ) -> None:
        """2026-08-10 用于在工具批处理结束后补写工具墙钟与本回合总耗时"""
        session = self._session_factory()
        row = session.get(AgentTurn, turn_id)
        if row is None:
            session.close()
            raise RuntimeError(f"agent turn 审计行不存在: {turn_id}")
        row.tool_wall_ms = tool_wall_ms
        row.turn_ms = turn_ms
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
            )
        )
        self._commit(session)


__all__ = ["AgentAuditRecorder"]
