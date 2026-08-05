"""
章节标注专用双阶段 LangGraph
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from .errors import AnnotationProtocolError
from .schema import ChapterAnnotation, ChapterAnnotationPatch
from .tools import AnnotationToolLedger

AnnotationPhase = Literal["running_current", "repair_initial", "after_open", "repair_post_after", "completed"]


class AnnotationGraphState(TypedDict):
    """2026-08-05 用于保存章节标注专用图的候选阶段与消息链"""

    messages: Annotated[list[BaseMessage], add_messages]
    phase: AnnotationPhase
    iterations: int
    candidate: dict[str, Any] | None
    initial_finish: dict[str, Any] | None
    final_annotation: dict[str, Any] | None
    revision_payload: dict[str, Any]
    error: str | None


def _unwrap_tool_payload(
    args: dict[str, Any],
    *,
    field_name: str,
) -> dict[str, Any]:
    """2026-08-05 用于严格解包 finish 与 revise_finish 的单一模型参数"""
    if set(args) != {field_name}:
        raise ValueError(f"工具参数必须且只能包含包装字段 {field_name}")
    payload = args[field_name]
    if not isinstance(payload, Mapping):
        raise ValueError(f"{field_name} 必须是对象")
    return dict(payload)


def _merge_patch(candidate: dict[str, Any], patch: ChapterAnnotationPatch) -> dict[str, Any]:
    """2026-08-05 用于只把 revise_finish 实际提交字段合并到当前完整候选"""
    merged = dict(candidate)
    merged.update(patch.model_dump(mode="json", exclude_unset=True))
    return merged


def _submission_call(state: AnnotationGraphState) -> dict[str, Any]:
    """2026-08-05 用于取得当前 Agent 消息中的唯一提交工具调用"""
    last_message = state["messages"][-1]
    calls = last_message.tool_calls if isinstance(last_message, AIMessage) else []
    submissions = [call for call in calls if call.get("name") in {"finish", "revise_finish"}]
    if len(calls) != 1 or len(submissions) != 1:
        raise ValueError("finish 或 revise_finish 必须在单独一轮中唯一调用")
    return dict(submissions[0])


def _build_agent_node(llm: Any, tools: list[Any], max_iterations: int):
    """2026-08-05 用于构建保留完整消息链并限制内部循环次数的模型节点"""

    async def agent_node(state: AnnotationGraphState) -> dict[str, Any]:
        """2026-08-05 用于执行一次绑定当前工具合同的模型调用"""
        iterations = int(state.get("iterations") or 0)
        if iterations >= max_iterations:
            return {"error": f"annotation LangGraph 内部循环达到上限 {max_iterations}"}
        response = await llm.bind_tools(tools).ainvoke(list(state["messages"]))
        return {"messages": [response], "iterations": iterations + 1}

    return agent_node


def _route_after_agent(state: AnnotationGraphState) -> str:
    """2026-08-05 用于按当前阶段和最新工具调用路由专用图"""
    if state.get("error"):
        return "end"
    last_message = state["messages"][-1]
    calls = last_message.tool_calls if isinstance(last_message, AIMessage) else []
    phase = state["phase"]
    names = [str(call.get("name")) for call in calls]

    if phase == "running_current":
        if not calls:
            return "repair_initial"
        if any(name in {"finish", "revise_finish"} for name in names):
            return "initial_finalize"
        if all(name in {"search", "pull", "push"} for name in names):
            return "current_tools"
        return "protocol_error"

    if phase == "repair_initial":
        return "initial_finalize" if names == ["revise_finish"] else "repair_initial"

    if phase == "after_open":
        if not calls:
            return "keep_initial"
        if names == ["revise_finish"]:
            return "post_finalize"
        if all(name in {"search", "read_chunk"} for name in names):
            return "after_tools"
        return "protocol_error"

    if phase == "repair_post_after":
        return "post_finalize" if names == ["revise_finish"] else "repair_post_after"

    return "end"


def _build_tools_node(tools: list[Any]):
    """2026-08-05 用于构建只执行非提交工具的 LangGraph 节点"""
    ordinary_tools = [candidate for candidate in tools if candidate.name not in {"finish", "revise_finish"}]
    tool_node = ToolNode(ordinary_tools, handle_tool_errors=False)

    async def run_tools(state: AnnotationGraphState) -> dict[str, Any]:
        """2026-08-05 用于执行当前阶段已通过路由门禁的普通工具调用"""
        return dict(await tool_node.ainvoke(state))

    return run_tools


def _build_repair_node(*, post_after: bool):
    """2026-08-05 用于构建初始或后文修正阶段的明确错误反馈节点"""

    def repair_node(state: AnnotationGraphState) -> dict[str, Any]:
        """2026-08-05 用于要求 Agent 通过局部 revise_finish 修正当前候选"""
        candidate = state.get("candidate")
        if candidate is None:
            message = "尚无完整候选，请先在单独一轮调用 finish 提交完整章节标注"
            phase: AnnotationPhase = "running_current"
        else:
            message = "上一份完整候选已保留，请只调用 revise_finish 提交实际变化字段"
            phase = "repair_post_after" if post_after else "repair_initial"
        return {"phase": phase, "messages": [SystemMessage(content=message)]}

    return repair_node


def _build_initial_finalize_node(
    *,
    ledger: AnnotationToolLedger,
    validator: Callable[[ChapterAnnotation, set[int]], None],
):
    """2026-08-05 用于构建首次 finish 与初始局部修正的完整校验节点"""

    def finalize_initial(state: AnnotationGraphState) -> dict[str, Any]:
        """2026-08-05 用于保存有效初始候选冻结业务输出并开放检索式 after"""
        candidate = state.get("candidate")
        call: dict[str, Any] | None = None
        try:
            call = _submission_call(state)
            name = str(call["name"])
            args = dict(call.get("args") or {})
            if name == "finish":
                candidate = _unwrap_tool_payload(args, field_name="annotation")
            else:
                if candidate is None:
                    raise ValueError("没有可供 revise_finish 修正的完整候选")
                patch_payload = _unwrap_tool_payload(args, field_name="correction")
                candidate = _merge_patch(candidate, ChapterAnnotationPatch.model_validate(patch_payload))
            annotation = ChapterAnnotation.model_validate(candidate)
            validator(annotation, {ledger.current_chapter_id} | ledger.visible_evidence_chapter_ids)
            ledger.freeze_business_results()
        except Exception as exc:  # noqa: BLE001
            return {
                "candidate": candidate,
                "phase": "repair_initial",
                "messages": [
                    SystemMessage(
                        content=(
                            f"初始 finish 校验失败: {exc}\n"
                            "候选已保留，只调用 revise_finish 提交实际变化字段"
                        )
                    )
                ],
            }

        if call is None:
            raise AnnotationProtocolError("初始提交调用缺失")
        tool_message = ToolMessage(
            content=(
                "初始章节标注已通过并冻结业务输出。after 原文不会批量注入；"
                "现在可用 search 检索固定的全部后续章节，用 read_chunk 读取本轮命中的 chunk，"
                "如无需修改则直接回复且不要调用工具"
            ),
            tool_call_id=str(call["id"]),
            name=str(call["name"]),
        )
        return {
            "candidate": annotation.model_dump(mode="json"),
            "initial_finish": annotation.model_dump(mode="json"),
            "phase": "after_open",
            "messages": [tool_message],
        }

    return finalize_initial


def _build_post_finalize_node(
    *,
    ledger: AnnotationToolLedger,
    validator: Callable[[ChapterAnnotation, set[int]], None],
):
    """2026-08-05 用于构建 after 检索后的局部修正校验节点"""

    def finalize_post(state: AnnotationGraphState) -> dict[str, Any]:
        """2026-08-05 用于合并实际修正字段并重新执行完整章节校验"""
        candidate = state.get("candidate")
        revision_payload = dict(state.get("revision_payload") or {})
        try:
            if candidate is None:
                raise ValueError("after 阶段缺少初始完整候选")
            call = _submission_call(state)
            if call.get("name") != "revise_finish":
                raise ValueError("after 阶段只允许 revise_finish")
            patch_payload = _unwrap_tool_payload(dict(call.get("args") or {}), field_name="correction")
            patch = ChapterAnnotationPatch.model_validate(patch_payload)
            candidate = _merge_patch(candidate, patch)
            revision_payload.update(patch.model_dump(mode="json", exclude_unset=True))
            annotation = ChapterAnnotation.model_validate(candidate)
            validator(annotation, {ledger.current_chapter_id, *ledger.after_chapter_ids})
        except Exception as exc:  # noqa: BLE001
            return {
                "candidate": candidate,
                "revision_payload": revision_payload,
                "phase": "repair_post_after",
                "messages": [
                    SystemMessage(
                        content=(
                            f"after revise_finish 校验失败: {exc}\n"
                            "必须继续调用 revise_finish 修正，不能用无工具响应绕过"
                        )
                    )
                ],
            }
        return {
            "candidate": annotation.model_dump(mode="json"),
            "final_annotation": annotation.model_dump(mode="json"),
            "revision_payload": revision_payload,
            "phase": "completed",
        }

    return finalize_post


def _keep_initial(state: AnnotationGraphState) -> dict[str, Any]:
    """2026-08-05 用于把 after 阶段无工具响应解释为保持初始 finish"""
    initial_finish = state.get("initial_finish")
    if initial_finish is None:
        return {"error": "after 阶段缺少 initial_finish"}
    return {
        "candidate": dict(initial_finish),
        "final_annotation": dict(initial_finish),
        "revision_payload": {},
        "phase": "completed",
    }


def _protocol_error(state: AnnotationGraphState) -> dict[str, Any]:
    """2026-08-05 用于直接拒绝当前阶段禁止的工具调用"""
    last_message = state["messages"][-1]
    calls = last_message.tool_calls if isinstance(last_message, AIMessage) else []
    names = [str(call.get("name")) for call in calls]
    return {"error": f"阶段 {state['phase']} 拒绝工具调用: {names}"}


def _route_after_terminal_node(state: AnnotationGraphState) -> str:
    """2026-08-05 用于在完成或错误状态下结束专用图"""
    if state.get("error") or state.get("final_annotation") is not None:
        return END
    return "agent"


def build_annotation_graph(
    llm: Any,
    tools: list[Any],
    *,
    ledger: AnnotationToolLedger,
    max_iterations: int,
    initial_validator: Callable[[ChapterAnnotation, set[int]], None],
    post_after_validator: Callable[[ChapterAnnotation, set[int]], None],
) -> Any:
    """2026-08-05 用于构建 running current 到 post after repair 的专用图"""
    graph = StateGraph(AnnotationGraphState)
    graph.add_node("agent", _build_agent_node(llm, tools, max_iterations))
    graph.add_node("current_tools", _build_tools_node(tools))
    graph.add_node("after_tools", _build_tools_node(tools))
    graph.add_node("repair_initial", _build_repair_node(post_after=False))
    graph.add_node("repair_post_after", _build_repair_node(post_after=True))
    graph.add_node(
        "initial_finalize",
        _build_initial_finalize_node(ledger=ledger, validator=initial_validator),
    )
    graph.add_node(
        "post_finalize",
        _build_post_finalize_node(ledger=ledger, validator=post_after_validator),
    )
    graph.add_node("keep_initial", _keep_initial)
    graph.add_node("protocol_error", _protocol_error)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        _route_after_agent,
        {
            "current_tools": "current_tools",
            "after_tools": "after_tools",
            "initial_finalize": "initial_finalize",
            "post_finalize": "post_finalize",
            "repair_initial": "repair_initial",
            "repair_post_after": "repair_post_after",
            "keep_initial": "keep_initial",
            "protocol_error": "protocol_error",
            "end": END,
        },
    )
    graph.add_edge("current_tools", "agent")
    graph.add_edge("after_tools", "agent")
    graph.add_edge("repair_initial", "agent")
    graph.add_edge("repair_post_after", "agent")
    for node_name in ("initial_finalize", "post_finalize", "keep_initial", "protocol_error"):
        graph.add_conditional_edges(
            node_name,
            _route_after_terminal_node,
            {"agent": "agent", END: END},
        )
    return graph.compile()
