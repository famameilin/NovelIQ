"""
章节标注逐 chunk 语义写入 LangGraph

消息链采用 messages + add_messages 累积；每次模型请求携带完整历史消息。
complete_chunk 与 finish_chapter 由程序自动执行：七个领域全部写入成功后
图节点自动冻结 chunk 并完成章节，模型不需要调用完成工具。
"""

from __future__ import annotations

import json
import time
from functools import partial
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from .errors import AnnotationInvariantError
from .tools import AnnotationToolLedger

if TYPE_CHECKING:
    from src.agents.audit.observer import AgentTurnObserver
    from src.agents.stream import AgentStream

AnnotationPhase = Literal["chunk_open", "continuity_open", "completed"]

_DOMAIN_NAMES = (
    "metrics",
    "entities",
    "character_observations",
    "dialogues",
    "events",
    "relations",
    "foreshadowings",
)
_DOMAIN_NAMES_SET = frozenset(_DOMAIN_NAMES)


class AnnotationGraphState(TypedDict):
    """2026-08-10 用于保存逐 chunk 工具循环的累积消息链"""

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
    observer: AgentTurnObserver | None = None,
    retries: int | None = None,
):
    """2026-08-10 用于构建同步系统阶段并限制循环次数的模型节点"""

    async def agent_node(state: AnnotationGraphState) -> dict[str, Any]:
        """2026-08-10 用于执行一次绑定语义工具合同的模型调用"""
        iterations = int(state.get("iterations") or 0)
        if iterations >= max_iterations:
            return {"error": f"annotation LangGraph 内部循环达到上限 {max_iterations}"}
        ledger.set_phase(state["phase"])
        if stream is not None:
            await stream.thinking(f"章节标注推理中（第 {iterations + 1} 轮）...")
        from src.agents.stream import run_model_call

        request_messages = list(state["messages"])
        context_summary = ledger.context_summary()
        turn_started_ns = time.perf_counter_ns()

        def on_turn_complete(message: AIMessage, timing: Any) -> None:
            """2026-08-10 用于在模型流结束后写入回合审计"""
            if observer is None:
                return
            observer.record_turn(
                context_summary=context_summary,
                request_messages=request_messages,
                response_message=message,
                timing=timing,
                started_ns=turn_started_ns,
            )

        try:
            response = await run_model_call(
                llm.bind_tools(tools),
                request_messages,
                stream,
                on_turn_complete=on_turn_complete,
                total_attempts=retries,
            )
        except Exception as exc:  # noqa: BLE001
            if observer is not None:
                observer.record_failed_turn(
                    context_summary=context_summary,
                    error=str(exc),
                    started_ns=turn_started_ns,
                    request_messages=request_messages,
                )
            raise
        return {"messages": [response], "iterations": iterations + 1}

    return agent_node


def _tool_calls(state: AnnotationGraphState) -> list[dict[str, Any]]:
    """2026-08-10 用于读取最后一条模型消息的工具调用列表"""
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        return []
    return [dict(call) for call in last_message.tool_calls]


def _route_after_agent(state: AnnotationGraphState) -> str:
    """2026-08-10 用于区分普通工具批次和无工具协议错误"""
    if state.get("error"):
        return "end"
    calls = _tool_calls(state)
    if not calls:
        return "protocol_error"
    return "tool_batch"


async def _invoke_tool(tool_map: dict[str, Any], call: dict[str, Any]) -> str:
    """2026-08-07 用于按模型工具调用执行同步或异步 LangChain 工具"""
    name = str(call.get("name"))
    candidate = tool_map.get(name)
    if candidate is None:
        raise ValueError(f"未知 annotation 工具: {name}")
    result = await candidate.ainvoke(dict(call.get("args") or {}))
    return str(result)


def _failed_receipt(name: str, error: str) -> str:
    """2026-08-10 用于构造单个调用失败时模型可见的独立回执"""
    return json.dumps(
        {"accepted": False, "tool": name, "error": str(error)},
        ensure_ascii=False,
    )


def _truncated_error(name: str) -> str:
    """2026-08-11 用于构造流截断调用不执行写入时模型可见的独立回执"""
    return (
        f"模型工具 {name} 的参数不完整（流传输截断，参数 JSON 在对象中间被切断），"
        "本次未执行任何写入，请重新提交完整参数。"
    )


def _build_tool_batch_node(
    tools: list[Any],
    *,
    ledger: AnnotationToolLedger,
    observer: AgentTurnObserver | None = None,
    stream: AgentStream | None = None,
):
    """2026-08-10 用于构建逐调用独立提交且互不回滚的工具节点"""
    tool_map = {candidate.name: candidate for candidate in tools}

    async def tool_batch(state: AnnotationGraphState) -> dict[str, Any]:
        """2026-08-10 用于按调用顺序执行工具；失败只恢复该调用前的 Ledger 与 FactGraph"""

        async def _emit_tool_status(name: str, status: str, message: str) -> None:
            """2026-08-12 用于推送工具结果状态事件；SSE 推送失败时先闭合回合审计计时再上抛"""
            if stream is None:
                return
            try:
                if status == "success":
                    await stream.tool_call_succeeded(name, message)
                else:
                    await stream.tool_call_failed(name, message)
            except Exception:
                if observer is not None:
                    observer.close_turn()
                raise

        calls = _tool_calls(state)
        messages: list[ToolMessage] = []
        for call_index, call in enumerate(calls):
            name = str(call.get("name"))
            if call.get("truncated"):
                error_text = _truncated_error(name)
                result = _failed_receipt(name, error_text)
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
                        response=json.loads(result),
                        receipt=json.loads(result),
                        status="error",
                        error=error_text,
                        tool_duration_ms=0,
                        started_ns=time.perf_counter_ns(),
                    )
                await _emit_tool_status(name, "error", "参数不完整（流传输截断）")
                messages.append(
                    ToolMessage(
                        content=result,
                        tool_call_id=str(call["id"]),
                        name=name,
                    )
                )
                continue
            ledger_snapshot = ledger.snapshot()
            graph_snapshot = (
                ledger.graph.snapshot() if ledger.graph is not None else None
            )
            started_ns = time.perf_counter_ns()
            try:
                if stream is not None:
                    await stream.tool_call_started(name)
                result = await _invoke_tool(tool_map, call)
                status = "success"
                error: str | None = None
                receipt = json.loads(result)
            except AnnotationInvariantError:
                # 合同违反属不可恢复错误：先闭合回合审计计时再上抛，避免 agent_turns 行耗时字段永久为空
                if observer is not None:
                    observer.close_turn()
                raise
            except Exception as exc:  # noqa: BLE001
                ledger.restore(ledger_snapshot)
                if graph_snapshot is not None and ledger.graph is not None:
                    ledger.graph.restore(graph_snapshot)
                ledger.errors.append(str(exc))
                result = _failed_receipt(name, str(exc))
                status = "error"
                error = str(exc)
                receipt = json.loads(result)
            tool_duration_ms = max(
                0, round((time.perf_counter_ns() - started_ns) / 1_000_000)
            )
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
                    response=receipt,
                    receipt=receipt,
                    status=status,
                    error=error,
                    tool_duration_ms=tool_duration_ms,
                    started_ns=started_ns,
                )
            if status == "success":
                await _emit_tool_status(name, "success", result)
            else:
                await _emit_tool_status(name, "error", error or "")
            messages.append(
                ToolMessage(
                    content=result,
                    tool_call_id=str(call["id"]),
                    name=name,
                )
            )
        if observer is not None:
            observer.close_turn()
        return {"messages": messages, "phase": ledger.phase}

    return tool_batch


def _build_auto_finalize_node(
    ledger: AnnotationToolLedger,
    *,
    stream: AgentStream | None = None,
    observer: AgentTurnObserver | None = None,
):
    """2026-08-10 用于七领域写入成功后自动 complete_chunk 并 finish_chapter"""

    async def auto_finalize(state: AnnotationGraphState) -> dict[str, Any]:
        """2026-08-10 用于在七领域 receipt 齐全时程序冻结 chunk 并完成章节"""
        if ledger.phase != "chunk_open":
            return {"phase": ledger.phase}
        if not _DOMAIN_NAMES_SET <= ledger.domain_receipts:
            return {"phase": ledger.phase}
        try:
            if stream is not None:
                await stream.tool_call_started("complete_chunk")
            ledger.complete_active_chunk()
            if stream is not None:
                await stream.tool_call_succeeded("complete_chunk", "chunk frozen")
                await stream.tool_call_started("finish_chapter")
            ledger.finish()
            if stream is not None:
                await stream.tool_call_succeeded("finish_chapter", "chapter completed")
        except Exception:
            # 章节完成写入失败时同样闭合审计计时，避免该回合耗时字段永久为空
            if observer is not None:
                observer.close_turn()
            raise
        return {"phase": ledger.phase}

    return auto_finalize


def _protocol_error(
    state: AnnotationGraphState,
    *,
    observer: AgentTurnObserver | None = None,
) -> dict[str, Any]:
    """2026-08-10 用于拒绝无工具回复并闭合当前回合审计计时"""
    if observer is not None:
        observer.close_turn()
    names = [str(call.get("name")) for call in _tool_calls(state)]
    return {
        "error": (
            "annotation 工具协议错误：必须调用工具，"
            f"实际={names}"
        )
    }


def _route_after_work(state: AnnotationGraphState) -> str:
    """2026-08-10 用于在完成章节或发生错误后结束图"""
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
    observer: AgentTurnObserver | None = None,
    retries: int | None = None,
) -> Any:
    """2026-08-10 用于构建逐 chunk 领域写入和章节自动完成状态机（消息链累积）"""
    graph = StateGraph(AnnotationGraphState)
    graph.add_node(
        "agent",
        _build_agent_node(
            llm,
            tools,
            ledger=ledger,
            max_iterations=max_iterations,
            stream=stream,
            observer=observer,
            retries=retries,
        ),
    )
    graph.add_node(
        "tool_batch",
        _build_tool_batch_node(
            tools,
            ledger=ledger,
            observer=observer,
            stream=stream,
        ),
    )
    graph.add_node(
        "auto_finalize",
        _build_auto_finalize_node(
            ledger,
            stream=stream,
            observer=observer,
        ),
    )
    graph.add_node(
        "protocol_error",
        partial(_protocol_error, observer=observer),
    )
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        _route_after_agent,
        {
            "tool_batch": "tool_batch",
            "protocol_error": "protocol_error",
            "end": END,
        },
    )
    graph.add_edge("tool_batch", "auto_finalize")
    for node_name in ("auto_finalize", "protocol_error"):
        graph.add_conditional_edges(
            node_name,
            _route_after_work,
            {"agent": "agent", END: END},
        )
    return graph.compile()


__all__ = ["AnnotationGraphState", "build_annotation_graph"]
