"""
创建时间: 2026-10-02
创建者: Trae
任务: 大文件拆分 src/agents/graph.py（finalize 校验段）
说明: 承接自 graph.py 的 finish 载荷解析/合并/重试消息构造与 finalize 节点
      工厂；_FINISH_TOOL_NAME 随迁并由 graph.py 导入复用，状态/路由/其余
      节点与 build_agent_graph 留在 graph.py，导入方零改动。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage

if TYPE_CHECKING:
    from src.agents.audit.observer import AgentTurnObserver
    from src.agents.graph import AgentLoopState
    from src.agents.stream import AgentStream

_FINISH_TOOL_NAME = "finish"


def _resolve_finish_payload_field(
    tools: list[Any],
    *,
    tool_name: str,
) -> str | None:
    """
    2026-08-02 用于从真实 finish 工具 schema 识别结构化结果包装字段
    """
    for candidate in tools:
        if getattr(candidate, "name", None) != tool_name:
            continue
        args_schema = getattr(candidate, "args_schema", None)
        model_fields = getattr(args_schema, "model_fields", None)
        if not isinstance(model_fields, dict) or len(model_fields) != 1:
            return None
        return next(iter(model_fields))
    return None


def _unwrap_finish_payload(
    finish_args: dict[str, Any],
    *,
    payload_field: str | None,
) -> dict[str, Any]:
    """
    2026-08-02 用于按真实 finish 工具 schema 严格解包单参数 Pydantic 模型
    """
    if payload_field is None:
        return finish_args
    if set(finish_args) != {payload_field}:
        raise ValueError(f"finish 工具参数必须且只能包含包装字段 {payload_field}")
    wrapped_payload = finish_args.get(payload_field)
    if not isinstance(wrapped_payload, Mapping):
        raise ValueError(f"finish 工具包装字段 {payload_field} 必须是对象")
    return dict(wrapped_payload)


def _merge_candidate_patch(
    candidate: dict[str, Any],
    patch: Any,
) -> dict[str, Any]:
    """
    2026-08-03 用于把局部修正字段合并到上一次完整候选结果
    """
    merged = dict(candidate)
    merged.update(patch.model_dump(exclude_unset=True, mode="json"))
    return merged


def _retry_messages(state: AgentLoopState, error_text: str) -> list[BaseMessage]:
    """
    2026-08-09 用于构造 finalize 失败重试消息：
    最后 AIMessage 的每条 tool_call 都追加对应 ToolMessage 响应，
    避免悬空 tool_calls 再次发送给 OpenAI 触发 400
    """
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return [SystemMessage(content=error_text)]
    return [
        ToolMessage(
            content=error_text,
            tool_call_id=str(call.get("id", "")),
            name=str(call.get("name", "")),
        )
        for call in last_message.tool_calls
    ]


def _build_finalize_node(
    max_attempts: int,
    response_model: type[Any],
    tool_name: str = _FINISH_TOOL_NAME,
    payload_field: str | None = None,
    response_validator: Callable[[Any], None] | None = None,
    revision_tool_name: str | None = None,
    revision_response_model: type[Any] | None = None,
    revision_payload_field: str | None = None,
    stream: AgentStream | None = None,
    observer: AgentTurnObserver | None = None,
):
    """构造 finalize 节点：提取 finish 工具参数并校验结构化输出，审计提交工具调用并闭合回合"""

    async def finalize_node(state: AgentLoopState) -> dict[str, Any]:
        """2026-08-02 用于只校验最新 Agent 消息中的唯一 finish 调用并阻止旧调用复用"""
        if stream is not None:
            try:
                await stream.thinking("校验最终结构化输出...")
            except Exception:
                # SSE 推送失败时先闭合上一条回合审计计时再上抛，避免 agent_turns 行耗时字段永久为空
                if observer is not None:
                    observer.close_turn()
                raise
        node_started_ns = time.perf_counter_ns()
        last_message = state["messages"][-1]
        tool_calls = last_message.tool_calls if isinstance(last_message, AIMessage) else []
        submission_tool_names = {tool_name}
        if revision_tool_name is not None:
            submission_tool_names.add(revision_tool_name)
        finish_calls = [call for call in tool_calls if call.get("name") in submission_tool_names]

        def close_submission_audit(
            *,
            call: Mapping[str, Any] | None,
            status: str = "success",
            error: str | None = None,
        ) -> None:
            """2026-08-11 用于记录提交工具调用审计并在任何收口路径闭合回合计时"""
            if observer is None:
                return
            if call is not None:
                observer.record_tool_call(
                    call_index=0,
                    tool_name=str(call.get("name")),
                    request_args=dict(call.get("args") or {}),
                    raw_args=(str(call.get("raw_args")) if call.get("raw_args") is not None else None),
                    response=({"accepted": True} if status == "success" else {"accepted": False, "error": error}),
                    receipt=None,
                    status=status,
                    error=error,
                    tool_duration_ms=max(
                        0,
                        round((time.perf_counter_ns() - node_started_ns) / 1_000_000),
                    ),
                    started_ns=node_started_ns,
                )
            observer.close_turn()

        if len(finish_calls) != 1 or len(tool_calls) != 1:
            error_msg = (
                f"agent 必须在单独一轮中唯一调用 {tool_name} 工具提交结果"
                if finish_calls
                else f"agent 未调用 {tool_name} 工具提交结果"
            )
            attempts = int(state.get("attempts") or 0) + 1
            close_submission_audit(
                call=finish_calls[0] if finish_calls else None,
                status="error",
                error=error_msg,
            )
            if attempts >= max_attempts:
                return {"attempts": attempts, "error": error_msg}
            can_revise = state.get("candidate") is not None and revision_tool_name is not None
            retry_instruction = (
                f"上一份完整候选结果已保留，请调用 {revision_tool_name} 只提交需要修改的字段，"
                "不要重复提交完整四阶段结果。"
                if can_revise
                else f"请调用 {tool_name} 工具提交完整结果。"
            )
            return {
                "attempts": attempts,
                "messages": _retry_messages(
                    state,
                    f"错误: {error_msg}。{retry_instruction}",
                ),
            }

        submission_call = finish_calls[0]
        submission_name = submission_call.get("name")
        candidate = state.get("candidate")
        candidate_for_state = candidate
        try:
            submission_args = submission_call.get("args") or {}
            if submission_name == tool_name:
                payload = _unwrap_finish_payload(
                    submission_args,
                    payload_field=payload_field,
                )
                candidate_for_state = payload
            elif submission_name == revision_tool_name:
                if revision_response_model is None:
                    raise ValueError("当前 Agent 未配置局部修正结构")
                if candidate is None:
                    raise ValueError(f"没有可修正的完整候选结果，请先调用 {tool_name} 提交完整结果")
                patch_payload = _unwrap_finish_payload(
                    submission_args,
                    payload_field=revision_payload_field,
                )
                patch = revision_response_model.model_validate(patch_payload)
                candidate_for_state = _merge_candidate_patch(candidate, patch)
            else:
                raise ValueError(f"不支持的结果提交工具: {submission_name}")
            parsed = response_model.model_validate(candidate_for_state)
            if response_validator is not None:
                response_validator(parsed)
        except Exception as exc:
            error_msg = f"finish 输出校验失败: {exc}"
            attempts = int(state.get("attempts") or 0) + 1
            close_submission_audit(
                call=submission_call,
                status="error",
                error=error_msg,
            )
            if attempts >= max_attempts:
                return {"attempts": attempts, "error": error_msg}
            can_revise = candidate_for_state is not None and revision_tool_name is not None
            retry_instruction = (
                f"上一份完整候选结果已保留，请调用 {revision_tool_name} 只提交需要修改的字段，"
                "不要重复提交完整四阶段结果。"
                if can_revise
                else f"请调用 {tool_name} 工具提交完整结果。"
            )
            update: dict[str, Any] = {
                "attempts": attempts,
                "messages": _retry_messages(
                    state,
                    f"错误: {error_msg}\n{retry_instruction}",
                ),
            }
            if candidate_for_state is not None:
                update["candidate"] = candidate_for_state
            return update

        close_submission_audit(call=submission_call, status="success")
        if stream is not None:
            # 2026-08-13 P2-7 补发 finish 工具终态事件：通用图路由把含 finish 的
            # 响应直接送 finalize、tools 节点不执行 finish，若不补发 succeeded，
            # 前端 finish 状态永远停在"进行中"（参照 annotation 图 auto_finalize
            # 对合成工具补发 started+succeeded 的写法；started 已由模型流推送）
            await stream.tool_call_succeeded(str(submission_name))
            await stream.output("最终结果已生成并通过校验")
        return {"output": parsed.model_dump(mode="json"), "error": None}

    return finalize_node
