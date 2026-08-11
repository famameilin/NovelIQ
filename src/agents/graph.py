"""
通用工具循环 Agent 图（LangGraph）

循环结构：
  agent（带工具 LLM）→ tools（执行工具）→ agent …
  当 agent 调用 finish 工具后 → finalize（校验结构化输出）
  finalize 校验失败 → 回 agent 重试（attempts 上限由配置控制）
"""

from __future__ import annotations

import time
from collections.abc import Callable, Collection, Mapping
from functools import partial
from typing import TYPE_CHECKING, Annotated, Any, TypedDict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from src.agents.stream import AgentStream, emit_tool_results, run_model_call

if TYPE_CHECKING:
    from src.agents.audit.observer import AgentTurnObserver


class AgentLoopState(TypedDict):
    """工具循环 agent 图状态"""

    messages: Annotated[list[BaseMessage], add_messages]
    attempts: int
    output: dict[str, Any] | None
    error: str | None
    candidate: dict[str, Any] | None
    tool_iterations: int


_FINISH_TOOL_NAME = "finish"


def _route_after_agent(
    state: AgentLoopState,
    *,
    submission_tool_names: Collection[str] = (_FINISH_TOOL_NAME,),
    max_tool_iterations: int,
) -> str:
    """agent 输出后路由：finish 进入校验，普通工具调用受迭代上限约束"""
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        names = {call["name"] for call in last.tool_calls}
        if names.intersection(submission_tool_names):
            return "finalize"
        next_iterations = int(state.get("tool_iterations") or 0) + len(last.tool_calls)
        if next_iterations > max_tool_iterations:
            return "tool_limit"
        return "tools"
    return "finalize"


def _route_after_tools(
    state: AgentLoopState,
    *,
    submission_tool_names: Collection[str] = (_FINISH_TOOL_NAME,),
) -> str:
    """tools 执行后路由：finish 已执行 → finalize；否则继续 agent"""
    last = state["messages"][-1]
    if isinstance(last, ToolMessage) and last.name in submission_tool_names:
        return "finalize"
    return "agent"


def _route_after_finalize(state: AgentLoopState) -> str:
    """finalize 校验失败且未超限时回 agent 重试"""
    if state.get("output") is not None or state.get("error") is not None:
        return END
    return "agent"


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
            await stream.thinking("校验最终结构化输出...")
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
                    raw_args=(
                        str(call.get("raw_args"))
                        if call.get("raw_args") is not None
                        else None
                    ),
                    response=(
                        {"accepted": True}
                        if status == "success"
                        else {"accepted": False, "error": error}
                    ),
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
        except Exception as exc:  # noqa: BLE001
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
            await stream.output("最终结果已生成并通过校验")
        return {"output": parsed.model_dump(mode="json"), "error": None}

    return finalize_node


def _build_agent_node(
    llm: Any,
    tools: list[Any],
    first_hint: str,
    stream: AgentStream | None = None,
    observer: AgentTurnObserver | None = None,
    context_summary: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
):
    """构造 agent 节点：绑定工具后调用 LLM（支持流式过程推送与回合审计）"""

    async def agent_node(state: AgentLoopState) -> dict[str, Any]:
        model_with_tools = llm.bind_tools(tools)
        messages = list(state["messages"])
        if not any(isinstance(message, HumanMessage) for message in messages):
            messages = [HumanMessage(content=first_hint)] + messages
        if stream is not None:
            await stream.thinking("正在推理，规划下一步动作...")
        turn_started_ns = time.perf_counter_ns()
        summary = (
            context_summary(state) if context_summary is not None else {"phase": "agent_loop"}
        )

        def on_turn_complete(message: AIMessage, timing: Any) -> None:
            """2026-08-10 用于在模型流结束后写入回合审计"""
            if observer is None:
                return
            observer.record_turn(
                context_summary=summary,
                request_messages=messages,
                response_message=message,
                timing=timing,
                started_ns=turn_started_ns,
            )

        try:
            response = await run_model_call(
                model_with_tools,
                messages,
                stream,
                on_turn_complete=on_turn_complete,
            )
        except Exception as exc:  # noqa: BLE001
            if observer is not None:
                observer.record_failed_turn(
                    context_summary=summary,
                    error=str(exc),
                    started_ns=turn_started_ns,
                    request_messages=messages,
                )
            raise
        return {"messages": [response]}

    return agent_node


def _invoke_tool(tool_map: dict[str, Any], call: Any) -> Any:
    """2026-08-10 用于按模型工具调用执行同步或异步 LangChain 工具"""
    name = str(call.get("name"))
    candidate = tool_map.get(name)
    if candidate is None:
        raise ValueError(f"未知 agent 工具: {name}")
    return candidate.ainvoke(dict(call.get("args") or {}))


def _build_tools_node(
    tool_map: dict[str, Any],
    *,
    observer: AgentTurnObserver | None = None,
    stream: AgentStream | None = None,
):
    """
    2026-08-10 用于执行工具并累计真实工具调用次数；启用审计时逐调用独立记录耗时
    """

    async def run_tools(state: AgentLoopState) -> dict[str, Any]:
        """2026-08-10 用于按调用顺序执行工具并更新工具循环计数"""
        last_message = state["messages"][-1]
        calls = list(last_message.tool_calls) if isinstance(last_message, AIMessage) else []
        messages: list[ToolMessage] = []
        for call_index, call in enumerate(calls):
            name = str(call.get("name"))
            started_ns = time.perf_counter_ns()
            if call.get("truncated"):
                result = (
                    f"Error: 工具 {name} 参数不完整（流传输截断，参数 JSON 在对象中间被切断），"
                    "本次未执行工具，请重新提交完整参数。"
                )
                status = "error"
                error: str | None = result
            else:
                try:
                    result = await _invoke_tool(tool_map, call)
                    status = "success"
                    error = None
                except Exception as exc:  # noqa: BLE001
                    result = f"Error: {exc}"
                    status = "error"
                    error = str(exc)
            tool_duration_ms = max(0, round((time.perf_counter_ns() - started_ns) / 1_000_000))
            if observer is not None:
                observer.record_tool_call(
                    call_index=call_index,
                    tool_name=name,
                    request_args=dict(call.get("args") or {}),
                    raw_args=(
                        str(call.get("raw_args"))
                        if call.get("raw_args") is not None
                        else None
                    ),
                    response={"result": str(result)[:2000]},
                    receipt=None,
                    status=status,
                    error=error,
                    tool_duration_ms=tool_duration_ms,
                    started_ns=started_ns,
                )
            messages.append(
                ToolMessage(
                    content=str(result),
                    tool_call_id=str(call.get("id", "")),
                    name=name,
                )
            )
        if observer is not None:
            observer.close_turn()
        if stream is not None:
            await emit_tool_results(stream, messages)
        return {
            "messages": messages,
            "tool_iterations": int(state.get("tool_iterations") or 0) + len(calls),
        }

    return run_tools


def _build_tool_limit_node(
    max_tool_iterations: int,
    *,
    observer: AgentTurnObserver | None = None,
):
    """
    2026-08-04 用于在工具调用达到配置上限前终止 Agent 循环
    """

    def tool_limit_node(state: AgentLoopState) -> dict[str, Any]:
        """
        2026-08-04 用于返回包含已执行次数的可审计循环上限错误
        """
        if observer is not None:
            observer.close_turn()
        return {
            "error": (
                f"agent 工具调用超过上限 {max_tool_iterations}，"
                f"已执行 {int(state.get('tool_iterations') or 0)} 次"
            )
        }

    return tool_limit_node


def build_agent_graph(
    llm: Any,
    tools: list[Any],
    *,
    max_attempts: int,
    response_model: type[Any],
    first_hint: str,
    finish_tool_name: str = _FINISH_TOOL_NAME,
    response_validator: Callable[[Any], None] | None = None,
    handle_tool_errors: bool | None = None,
    revision_tool_name: str | None = None,
    revision_response_model: type[Any] | None = None,
    max_tool_iterations: int | None = None,
    stream: AgentStream | None = None,
    observer: AgentTurnObserver | None = None,
    context_summary: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
) -> Any:
    """构建通用工具循环 agent 图"""
    graph = StateGraph(AgentLoopState)
    finish_payload_field = _resolve_finish_payload_field(tools, tool_name=finish_tool_name)
    revision_payload_field = (
        _resolve_finish_payload_field(tools, tool_name=revision_tool_name)
        if revision_tool_name is not None
        else None
    )
    if (revision_tool_name is None) != (revision_response_model is None):
        raise ValueError("局部修正工具名和局部修正响应模型必须同时配置")
    resolved_max_tool_iterations = max(1, max_tool_iterations or max_attempts)
    submission_tool_names = frozenset(
        {finish_tool_name, revision_tool_name} if revision_tool_name is not None else {finish_tool_name}
    )

    graph.add_node(
        "agent",
        _build_agent_node(
            llm,
            tools,
            first_hint,
            stream=stream,
            observer=observer,
            context_summary=context_summary,
        ),
    )
    tool_map = {candidate.name: candidate for candidate in tools}
    graph.add_node(
        "tools",
        _build_tools_node(
            tool_map,
            observer=observer,
            stream=stream,
        ),
    )
    graph.add_node("tool_limit", _build_tool_limit_node(resolved_max_tool_iterations, observer=observer))
    graph.add_node(
        "finalize",
        _build_finalize_node(
            max_attempts,
            response_model,
            finish_tool_name,
            finish_payload_field,
            response_validator,
            revision_tool_name,
            revision_response_model,
            revision_payload_field,
            stream=stream,
            observer=observer,
        ),
    )

    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        partial(
            _route_after_agent,
            submission_tool_names=submission_tool_names,
            max_tool_iterations=resolved_max_tool_iterations,
        ),
        {"tools": "tools", "finalize": "finalize", "tool_limit": "tool_limit"},
    )
    graph.add_conditional_edges(
        "tools",
        partial(_route_after_tools, submission_tool_names=submission_tool_names),
        {"agent": "agent", "finalize": "finalize"},
    )
    graph.add_conditional_edges("finalize", _route_after_finalize, {"agent": "agent", END: END})
    graph.add_edge("tool_limit", END)

    return graph.compile()
