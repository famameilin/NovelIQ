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
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from src.agents.graph_finalize import _FINISH_TOOL_NAME, _build_finalize_node, _resolve_finish_payload_field
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


def _build_agent_node(
    llm: Any,
    tools: list[Any],
    first_hint: str,
    stream: AgentStream | None = None,
    observer: AgentTurnObserver | None = None,
    context_summary: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
    retries: int | None = None,
):
    """构造 agent 节点：绑定工具后调用 LLM（支持流式过程推送与回合审计）"""

    async def agent_node(state: AgentLoopState) -> dict[str, Any]:
        model_with_tools = llm.bind_tools(tools)
        messages = list(state["messages"])
        if not any(isinstance(message, HumanMessage) for message in messages):
            messages = [HumanMessage(content=first_hint)] + messages
        if stream is not None:
            await stream.thinking("正在推理，规划下一步动作...")
        summary = context_summary(state) if context_summary is not None else {"phase": "agent_loop"}

        def on_turn_started(provider_request: dict[str, Any], started_ns: int) -> None:
            """2026-08-30 用于在通用 Agent 的物理 Provider 请求发送前写入独立审计行"""
            if observer is None:
                return
            observer.begin_provider_turn(
                context_summary=summary,
                request_messages=messages,
                provider_request=provider_request,
                started_ns=started_ns,
            )

        def on_turn_complete(message: AIMessage, timing: Any) -> None:
            """2026-08-30 用于收口通用 Agent 的成功物理 Provider 请求审计"""
            if observer is None:
                return
            observer.complete_provider_turn(response_message=message, timing=timing)

        def on_turn_failed(error: str, timing: Any, message: AIMessage | None) -> None:
            """2026-08-30 用于收口通用 Agent 的断流超时和无工具物理请求审计"""
            if observer is None:
                return
            observer.fail_provider_turn(error=error, timing=timing, response_message=message)

        response = await run_model_call(
            model_with_tools,
            messages,
            stream,
            on_turn_complete=on_turn_complete,
            on_turn_started=on_turn_started,
            on_turn_failed=on_turn_failed,
            total_attempts=retries,
        )
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
                except Exception as exc:
                    result = f"Error: {exc}"
                    status = "error"
                    error = str(exc)
            tool_duration_ms = max(0, round((time.perf_counter_ns() - started_ns) / 1_000_000))
            if observer is not None:
                observer.record_tool_call(
                    call_index=call_index,
                    tool_name=name,
                    request_args=dict(call.get("args") or {}),
                    raw_args=(str(call.get("raw_args")) if call.get("raw_args") is not None else None),
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
                f"agent 工具调用超过上限 {max_tool_iterations}，已执行 {int(state.get('tool_iterations') or 0)} 次"
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
    revision_tool_name: str | None = None,
    revision_response_model: type[Any] | None = None,
    max_tool_iterations: int | None = None,
    stream: AgentStream | None = None,
    observer: AgentTurnObserver | None = None,
    context_summary: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
    model_retries: int | None = None,
) -> Any:
    """构建通用工具循环 agent 图"""
    graph = StateGraph(AgentLoopState)
    finish_payload_field = _resolve_finish_payload_field(tools, tool_name=finish_tool_name)
    revision_payload_field = (
        _resolve_finish_payload_field(tools, tool_name=revision_tool_name) if revision_tool_name is not None else None
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
            retries=model_retries,
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
