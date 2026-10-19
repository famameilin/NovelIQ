"""
Agent 审计记录器（Annotation 与 Diagnosis 共用）

审计事实全部落到三张宽表：
- agent 保存每个真实 invocation 的终态并直接携带归属（run、执行角色、
  标注章或案例锚）；没有模型请求的派发失败只写执行终态，不伪造 turn=0
- agent_loop 保存每条真实模型请求：Agent 上下文（agent_id+turn_index）或
  standalone 上下文恰一；用量分项、供应商实报总量、费用、五类计时与四类通信/
  观察文档都是本表明确列，审计消息键直接落在可空唯一列上
- agent_toolcall 保存每次真实外层工具调用：原始参数与实际执行参数分开，
  耗时与四类观察文档同列保存
每次审计写入使用独立短事务即时提交，不随候选状态或最终标注事务回滚；
审计写入失败直接抛出异常终止 Agent，不静默忽略。
"""

from __future__ import annotations

from typing import Any


class AgentAuditRecorder:
    """以独立短事务持久化 Agent 审计数据"""

    def __init__(self, storage_factory):
        """绑定每次审计写入的独立 Session 工厂"""
        self._storage_factory = storage_factory

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
        """在派发时登记真实执行事实（含未发出请求就失败的尝试）

        invocation 必须直接给出归属（run 与执行角色，标注角色再带章、案例角色
        带案例锚）；归属缺失即合同违约，直接报错。返回值仍是观察器使用的本地
        句柄（执行身份以 agent_id 为准）。
        """
        return self._storage_factory().audit.start_invocation(
            agent_id=agent_id,
            task_type=task_type,
            attempt_number=attempt_number,
            run_id=run_id,
            role=role,
            chapter_id=chapter_id,
            case_anchor=case_anchor,
            **_,
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
        """在物理 Provider 请求发出前创建独立运行中模型调用

        run/章节/角色只用于在缺登记时补齐执行归属；调用行（身份、请求消息、
        审计上下文与起始计时备注）全部落在 agent_loop 宽行上，返回 call_id
        作为后续收口句柄。
        """
        return self._storage_factory().audit.start_turn(
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
        """按物理 Provider 请求结束状态补齐响应计时错误与 token 计账"""
        return self._storage_factory().audit.finish_turn(
            turn_id,
            raw_response=raw_response,
            error=error,
            timing=timing,
            timing_notes=timing_notes,
            token_usage=token_usage,
        )

    def update_turn_timings(self, turn_id: str, *, tool_wall_ms: int | None, turn_ms: int | None) -> None:
        """在工具批处理结束后补写工具墙钟与本回合总耗时

        turn_ms 是按现有 model_ms + tool_wall_ms 规则的重放投影（读取时计算），
        这里只登记实际测得的 tool_wall_ms；调用的 finished_at 随工具批处理结束更新。
        """
        return self._storage_factory().audit.update_turn_timings(turn_id, tool_wall_ms=tool_wall_ms, turn_ms=turn_ms)

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
        """在独立短事务中写入单次工具调用审计（含原始参数片段）

        turn_id 即真实模型调用的 call_id；实际执行参数与原始参数字符串分开保存，
        观察文档与耗时同列落在 agent_toolcall 宽行上。
        """
        return self._storage_factory().audit.record_tool_call(
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
        """把执行收口为真实终态

        没有发出任何模型请求的派发失败也只写执行记录（不伪造第 0 个模型回合）；
        成功尝试同样登记成功终态，模型请求事实仍只在其调用行上。
        重放幂等由终态相等承担：同状态同错误重复收口不报错，不同结果报错。
        """
        return self._storage_factory().audit.finish_invocation(
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
