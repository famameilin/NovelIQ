"""
章节内 agent 会话图：程序执行、结束请求与程序完整性检查
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph

from src.agents.annotation.ledger import AnnotationToolLedger

from .graph import AnnotationGraphState, _build_agent_node, _tool_calls
from .tool_batch import _build_tool_batch_node

if TYPE_CHECKING:
    from src.agents.stream import AgentStream
    from src.agents.turn_observer import AgentTurnObserver

    from .agent_ir import AgentAnnotation


def _route_after_agent_agent(state: AnnotationGraphState) -> str:
    """无工具响应也是结束请求，交给程序完整性检查"""
    if state.get("error") or state.get("halted"):
        return "end"
    if not _tool_calls(state):
        return "check"
    return "tool_batch"


def _route_after_check(state: AnnotationGraphState) -> str:
    """完整则结束，否则把缺口提示带回同一模型会话"""
    return "end" if state.get("completion_ok") or state.get("error") else "agent"


def build_agent_graph(
    llm: Any,
    program_tool: Any,
    finish_tool: Any,
    *,
    ledger: AnnotationToolLedger,
    agent: AgentAnnotation,
    max_iterations: int,
    stream: AgentStream | None = None,
    observer: AgentTurnObserver | None = None,
    retries: int | None = None,
    completion_check: Callable[[], list[str]] | None = None,
    thinking_message: Callable[[int], str] | None = None,
) -> Any:
    """构建独立 work 会话；finish 和无工具响应都进入同一完整性检查节点

    thinking_message：调用侧省略时保持章节标注文案；诊断等复用面传入 own 文案。
    """
    bind_tools = [program_tool, finish_tool]
    program_tool_name = str(program_tool.name)
    graph = StateGraph(AnnotationGraphState)
    graph.add_node(
        "agent",
        _build_agent_node(
            llm,
            bind_tools,
            ledger=ledger,
            max_iterations=max_iterations,
            stream=stream,
            observer=observer,
            retries=retries,
            thinking_message=thinking_message,
        ),
    )
    execute_batch = _build_tool_batch_node(
        bind_tools,
        ledger=ledger,
        observer=observer,
        stream=stream,
        program_tool_name=program_tool_name,
    )

    async def tool_batch(state: AnnotationGraphState) -> dict[str, Any]:
        ledger.end_requested = False
        result = await execute_batch(state)
        return result

    def route_batch(state: AnnotationGraphState) -> str:
        return "check" if ledger.end_requested else "agent"

    def check(state: AnnotationGraphState) -> dict[str, Any]:
        end_signal = "finish" if ledger.end_requested else "no_tool"
        if observer is not None:
            observer.close_turn()
        if completion_check is None:
            return {"completion_ok": False, "error": "未装配 work 完整性检查"}
        missing = list(completion_check())
        if not missing:
            return {"completion_ok": True, "missing": [], "end_signal": end_signal}
        ledger.end_requested = False
        return {
            "completion_ok": False,
            "missing": missing,
            "end_signal": end_signal,
            "messages": [
                HumanMessage(
                    content=(
                        "程序检查到当前 Agent 仍有缺口，请在同一会话补齐后再次结束：\n"
                        + "\n".join(f"- {item}" for item in missing)
                    )
                )
            ],
        }

    graph.add_node("tool_batch", tool_batch)
    graph.add_node("check", check)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        _route_after_agent_agent,
        {
            "tool_batch": "tool_batch",
            "check": "check",
            "end": END,
        },
    )
    graph.add_conditional_edges("tool_batch", route_batch, {"agent": "agent", "check": "check"})
    graph.add_conditional_edges("check", _route_after_check, {"agent": "agent", "end": END})
    return graph.compile()
