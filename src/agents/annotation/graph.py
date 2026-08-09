"""
章节标注逐 chunk 语义写入 LangGraph
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from .tools import AnnotationToolLedger

if TYPE_CHECKING:
    from src.agents.stream import AgentStream

AnnotationPhase = Literal["chunk_open", "continuity_open", "completed"]
_FINALIZER_NAMES = {"complete_chunk", "finish_chapter"}


class AnnotationGraphState(TypedDict):
    """2026-08-07 用于保存逐 chunk 工具循环和消息链"""

    messages: Annotated[list[BaseMessage], add_messages]
    phase: AnnotationPhase
    iterations: int
    error: str | None


def _build_agent_node(
    llm: Any,
    tools: list[Any],
    *,
    ledger: AnnotationToolLedger,
    max_iterations: int,
    stream: AgentStream | None = None,
):
    """2026-08-07 用于构建同步系统阶段并限制循环次数的模型节点"""

    async def agent_node(state: AnnotationGraphState) -> dict[str, Any]:
        """2026-08-07 用于执行一次绑定语义工具合同的模型调用"""
        iterations = int(state.get("iterations") or 0)
        if iterations >= max_iterations:
            return {"error": f"annotation LangGraph 内部循环达到上限 {max_iterations}"}
        ledger.set_phase(state["phase"])
        if stream is not None:
            await stream.thinking(f"章节标注推理中（第 {iterations + 1} 轮）...")
        from src.agents.stream import run_model_call

        response = await run_model_call(llm.bind_tools(tools), list(state["messages"]), stream)
        return {"messages": [response], "iterations": iterations + 1}

    return agent_node


def _tool_calls(state: AnnotationGraphState) -> list[dict[str, Any]]:
    """2026-08-07 用于读取最后一条模型消息的工具调用列表"""
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        return []
    return [dict(call) for call in last_message.tool_calls]


def _route_after_agent(state: AnnotationGraphState) -> str:
    """2026-08-07 用于区分普通工具批次和单独完成工具"""
    if state.get("error"):
        return "end"
    calls = _tool_calls(state)
    if not calls:
        return "protocol_error"
    names = [str(call.get("name")) for call in calls]
    finalizers = [name for name in names if name in _FINALIZER_NAMES]
    if finalizers:
        if len(calls) != 1:
            return "protocol_error"
        return "finalizer"
    return "tool_batch"


async def _invoke_tool(tool_map: dict[str, Any], call: dict[str, Any]) -> str:
    """2026-08-07 用于按模型工具调用执行同步或异步 LangChain 工具"""
    name = str(call.get("name"))
    candidate = tool_map.get(name)
    if candidate is None:
        raise ValueError(f"未知 annotation 工具: {name}")
    result = await candidate.ainvoke(dict(call.get("args") or {}))
    return str(result)


def _build_tool_batch_node(
    tools: list[Any],
    *,
    ledger: AnnotationToolLedger,
    stream: AgentStream | None = None,
):
    """2026-08-07 用于构建按调用顺序执行且整批可回滚的工具节点"""
    tool_map = {candidate.name: candidate for candidate in tools}

    async def tool_batch(state: AnnotationGraphState) -> dict[str, Any]:
        """2026-08-07 用于执行普通工具批次并在任一失败时恢复账本"""
        calls = _tool_calls(state)
        snapshot = ledger.snapshot()
        messages: list[BaseMessage] = []
        try:
            for call in calls:
                name = str(call.get("name"))
                if stream is not None:
                    await stream.tool_call_started(name)
                result = await _invoke_tool(tool_map, call)
                if stream is not None:
                    await stream.tool_call_succeeded(name, result)
                messages.append(
                    ToolMessage(
                        content=result,
                        tool_call_id=str(call["id"]),
                        name=name,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            ledger.restore(snapshot)
            if stream is not None:
                await stream.tool_call_failed(str(call.get("name") or "unknown"), str(exc))
            messages = [
                ToolMessage(
                    content=json.dumps(
                        {
                            "accepted": False,
                            "rolled_back": True,
                            "error": str(exc),
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id=str(call["id"]),
                    name=str(call["name"]),
                )
                for call in calls
            ]
            messages.append(
                SystemMessage(
                    content=(
                        f"本轮工具批次已整体回滚: {exc}\n"
                        "修正参数后重新提交受影响的完整领域"
                    )
                )
            )
        return {"messages": messages, "phase": ledger.phase}

    return tool_batch


def _build_finalizer_node(
    tools: list[Any],
    *,
    ledger: AnnotationToolLedger,
    stream: AgentStream | None = None,
):
    """2026-08-07 用于构建 complete_chunk 和 finish_chapter 单独执行节点"""
    tool_map = {candidate.name: candidate for candidate in tools}

    async def finalizer(state: AnnotationGraphState) -> dict[str, Any]:
        """2026-08-07 用于执行完成工具并注入连续性阶段消息"""
        call = _tool_calls(state)[0]
        name = str(call.get("name"))
        snapshot = ledger.snapshot()
        try:
            if stream is not None:
                await stream.tool_call_started(name)
            result = await _invoke_tool(tool_map, call)
            if stream is not None:
                await stream.tool_call_succeeded(name, result)
        except Exception as exc:  # noqa: BLE001
            ledger.restore(snapshot)
            if stream is not None:
                await stream.tool_call_failed(name, str(exc))
            return {
                "messages": [
                    ToolMessage(
                        content=json.dumps(
                            {"accepted": False, "error": str(exc)},
                            ensure_ascii=False,
                        ),
                        tool_call_id=str(call["id"]),
                        name=name,
                    ),
                    SystemMessage(
                        content=f"{name} 校验失败: {exc}",
                    ),
                ],
                "phase": ledger.phase,
            }

        messages: list[BaseMessage] = [
            ToolMessage(
                content=result,
                tool_call_id=str(call["id"]),
                name=name,
            )
        ]
        if name == "complete_chunk":
            messages.append(
                SystemMessage(
                    content=(
                        "全部 chunk 已冻结，可处理连续性。"
                        "可继续处理活动连续性案例；"
                        "后文只用于 resolve_case，不能修改正式标注。"
                        "处理完成后最后单独调用 finish_chapter"
                    )
                )
            )
        return {"messages": messages, "phase": ledger.phase}

    return finalizer


def _protocol_error(state: AnnotationGraphState) -> dict[str, Any]:
    """2026-08-07 用于拒绝无工具回复和混合完成工具调用"""
    names = [str(call.get("name")) for call in _tool_calls(state)]
    return {
        "error": (
            "annotation 工具协议错误：必须调用工具；"
            "complete_chunk 和 finish_chapter 必须单独调用，"
            f"实际={names}"
        )
    }


def _route_after_work(state: AnnotationGraphState) -> str:
    """2026-08-07 用于在完成章节或发生错误后结束图"""
    if state.get("error") or state["phase"] == "completed":
        return END
    return "agent"


def build_annotation_graph(
    llm: Any,
    tools: list[Any],
    *,
    ledger: AnnotationToolLedger,
    max_iterations: int,
    stream: AgentStream | None = None,
) -> Any:
    """2026-08-07 用于构建逐 chunk 领域写入和章节完成状态机"""
    graph = StateGraph(AnnotationGraphState)
    graph.add_node(
        "agent",
        _build_agent_node(
            llm,
            tools,
            ledger=ledger,
            max_iterations=max_iterations,
            stream=stream,
        ),
    )
    graph.add_node(
        "tool_batch",
        _build_tool_batch_node(tools, ledger=ledger, stream=stream),
    )
    graph.add_node(
        "finalizer",
        _build_finalizer_node(tools, ledger=ledger, stream=stream),
    )
    graph.add_node("protocol_error", _protocol_error)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        _route_after_agent,
        {
            "tool_batch": "tool_batch",
            "finalizer": "finalizer",
            "protocol_error": "protocol_error",
            "end": END,
        },
    )
    for node_name in ("tool_batch", "finalizer", "protocol_error"):
        graph.add_conditional_edges(
            node_name,
            _route_after_work,
            {"agent": "agent", END: END},
        )
    return graph.compile()


__all__ = ["AnnotationGraphState", "build_annotation_graph"]
