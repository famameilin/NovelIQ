"审计事实的完整短事务接口"

from __future__ import annotations

from typing import Any

from src.storage.input_boundary import plain_inputs
from src.storage.repositories.audit_repository import AuditRepository


@plain_inputs
class AuditAccess:
    def __init__(self, runner):
        self._runner = runner

    def start_invocation(
        self,
        *,
        agent_id: str | None = None,
        task_type: str | None = None,
        attempt_number: int = 1,
        run_id: str | None = None,
        role: str | None = None,
        chapter_id: int | None = None,
        case_anchor: str | None = None,
        **_: Any,
    ) -> int:
        "保存一项完整审计事实，成功提交后才返回"
        return self._runner.run(
            lambda session: AuditRepository(session).start_invocation(
                agent_id=agent_id,
                task_type=task_type,
                attempt_number=attempt_number,
                run_id=run_id,
                role=role,
                chapter_id=chapter_id,
                case_anchor=case_anchor,
                **_,
            )
        )

    def start_turn(
        self,
        *,
        run_id: str,
        task_type: str,
        call_type: str,
        model: str,
        agent_id: str,
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
        "保存一项完整审计事实，成功提交后才返回"
        return self._runner.run(
            lambda session: AuditRepository(session).start_turn(
                run_id=run_id,
                task_type=task_type,
                call_type=call_type,
                model=model,
                agent_id=agent_id,
                attempt_number=attempt_number,
                chapter_id=chapter_id,
                role=role,
                turn_index=turn_index,
                context_summary=context_summary,
                request_messages=request_messages,
                case_anchor=case_anchor,
                message_key=message_key,
                invocation_id=invocation_id,
            )
        )

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
        "保存一项完整审计事实，成功提交后才返回"
        return self._runner.run(
            lambda session: AuditRepository(session).finish_turn(
                turn_id,
                raw_response=raw_response,
                error=error,
                timing=timing,
                timing_notes=timing_notes,
                token_usage=token_usage,
            )
        )

    def update_turn_timings(self, turn_id: str, *, tool_wall_ms: int | None, turn_ms: int | None) -> None:
        "保存一项完整审计事实，成功提交后才返回"
        return self._runner.run(
            lambda session: AuditRepository(session).update_turn_timings(
                turn_id, tool_wall_ms=tool_wall_ms, turn_ms=turn_ms
            )
        )

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
        "保存一项完整审计事实，成功提交后才返回"
        return self._runner.run(
            lambda session: AuditRepository(session).record_tool_call(
                turn_id=turn_id,
                call_index=call_index,
                tool_name=tool_name,
                request_args=request_args,
                raw_args=raw_args,
                response=response,
                receipt=receipt,
                error=error,
                tool_duration_ms=tool_duration_ms,
                message_key=message_key,
            )
        )

    def finish_invocation(
        self,
        *,
        agent_id: str,
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
        "保存一项完整审计事实，成功提交后才返回"
        return self._runner.run(
            lambda session: AuditRepository(session).finish_invocation(
                agent_id=agent_id,
                status=status,
                task_type=task_type,
                attempt_number=attempt_number,
                run_id=run_id,
                role=role,
                chapter_id=chapter_id,
                case_anchor=case_anchor,
                final_error=final_error,
                message_key=message_key,
                **_,
            )
        )
