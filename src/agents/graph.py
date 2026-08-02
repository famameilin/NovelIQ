"""
通用工具循环 Agent 图（LangGraph）

循环结构：
  agent（带工具 LLM）→ tools（执行工具）→ agent …
  当 agent 调用 finish 工具后 → finalize（校验结构化输出）
  finalize 校验失败 → 回 agent 重试（attempts 上限由配置控制）
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode


class AgentLoopState(TypedDict):
    """工具循环 agent 图状态"""

    messages: Annotated[list[BaseMessage], add_messages]
    attempts: int
    output: dict[str, Any] | None
    error: str | None


_FINISH_TOOL_NAME = "finish"


def _route_after_agent(state: AgentLoopState) -> str:
    """agent 输出后路由：有 finish 调用 → finalize；有其它工具调用 → tools；否则 finalize 报错"""
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        names = {call["name"] for call in last.tool_calls}
        if _FINISH_TOOL_NAME in names:
            return "finalize"
        return "tools"
    return "finalize"


def _route_after_tools(state: AgentLoopState) -> str:
    """tools 执行后路由：finish 已执行 → finalize；否则继续 agent"""
    last = state["messages"][-1]
    if isinstance(last, ToolMessage) and last.name == _FINISH_TOOL_NAME:
        return "finalize"
    return "agent"


def _route_after_finalize(state: AgentLoopState) -> str:
    """finalize 校验失败且未超限时回 agent 重试"""
    if state.get("output") is not None or state.get("error") is not None:
        return END
    return "agent"


def _build_finalize_node(max_attempts: int, response_model: type[Any], tool_name: str = _FINISH_TOOL_NAME):
    """构造 finalize 节点：提取 finish 工具参数并校验结构化输出"""

    async def finalize_node(state: AgentLoopState) -> dict[str, Any]:
        finish_args: dict[str, Any] | None = None
        for message in reversed(state["messages"]):
            if isinstance(message, ToolMessage) and message.name == tool_name:
                finish_args = message.content if isinstance(message.content, dict) else None
                break
            if isinstance(message, AIMessage) and message.tool_calls:
                for call in reversed(message.tool_calls):
                    if call.get("name") == tool_name:
                        finish_args = call.get("args") or {}
                        break
                if finish_args is not None:
                    break

        if finish_args is None:
            error_msg = f"agent 未调用 {tool_name} 工具提交结果"
            attempts = int(state.get("attempts") or 0) + 1
            if attempts >= max_attempts:
                return {"attempts": attempts, "error": error_msg}
            return {
                "attempts": attempts,
                "messages": [
                    SystemMessage(content=f"错误: {error_msg}。请调用 {tool_name} 工具提交完整结果。")
                ],
            }

        try:
            parsed = response_model.model_validate(finish_args)
        except Exception as exc:  # noqa: BLE001
            error_msg = f"finish 输出校验失败: {exc}"
            attempts = int(state.get("attempts") or 0) + 1
            if attempts >= max_attempts:
                return {"attempts": attempts, "error": error_msg}
            return {
                "attempts": attempts,
                "messages": [
                    SystemMessage(content=f"错误: {error_msg}\n请修正后重新调用 {tool_name} 工具。")
                ],
            }

        return {"output": parsed.model_dump(mode="json"), "error": None}

    return finalize_node


def _build_agent_node(llm: Any, tools: list[Any], first_hint: str):
    """构造 agent 节点：绑定工具后调用 LLM"""

    async def agent_node(state: AgentLoopState) -> dict[str, Any]:
        model_with_tools = llm.bind_tools(tools)
        messages = list(state["messages"])
        if not any(isinstance(message, HumanMessage) for message in messages):
            messages = [HumanMessage(content=first_hint)] + messages
        response = await model_with_tools.ainvoke(messages)
        return {"messages": [response]}

    return agent_node


def build_agent_graph(
    llm: Any,
    tools: list[Any],
    *,
    max_attempts: int,
    response_model: type[Any],
    first_hint: str,
    finish_tool_name: str = _FINISH_TOOL_NAME,
) -> Any:
    """构建通用工具循环 agent 图"""
    graph = StateGraph(AgentLoopState)

    graph.add_node("agent", _build_agent_node(llm, tools, first_hint))
    graph.add_node("tools", ToolNode(tools))
    graph.add_node("finalize", _build_finalize_node(max_attempts, response_model, finish_tool_name))

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", _route_after_agent, {"tools": "tools", "finalize": "finalize"})
    graph.add_conditional_edges("tools", _route_after_tools, {"agent": "agent", "finalize": "finalize"})
    graph.add_conditional_edges("finalize", _route_after_finalize, {"agent": "agent", END: END})

    return graph.compile()
