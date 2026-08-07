"""
章节标注专用分阶段 LangGraph
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from .errors import AnnotationProtocolError
from .schema import ChapterFinish, ChapterFinishPatch, ChunkFinishPatch, EntityDirectoryPatch
from .tools import AnnotationToolLedger

AnnotationPhase = Literal[
    "current_open",
    "repair_current",
    "future_open",
    "repair_future",
    "future_finalize",
    "completed",
]

_ENTITY_FIELDS = ("characters", "locations", "objects", "organizations")
_FACT_FIELDS = (
    "character_observations",
    "location_observations",
    "dialogues",
    "events",
    "relations",
    "states",
    "foreshadowings",
)
_CURRENT_TOOL_NAMES = {
    "search_graph",
    "search_text",
    "read_text",
    "search_pool",
    "pull",
    "push",
}
_FUTURE_TOOL_NAMES = {
    "search_graph",
    "search_text",
    "read_text",
    "search_pool",
    "pull",
}


class AnnotationGraphState(TypedDict):
    """2026-08-07 用于保存章节标注候选阶段修订和消息链"""

    messages: Annotated[list[BaseMessage], add_messages]
    phase: AnnotationPhase
    iterations: int
    candidate: dict[str, Any] | None
    initial_finish: dict[str, Any] | None
    final_finish: dict[str, Any] | None
    revision_payloads: list[dict[str, Any]]
    error: str | None


def _unwrap_tool_payload(
    args: dict[str, Any],
    *,
    field_name: str,
) -> dict[str, Any]:
    """2026-08-07 用于严格解包 finish 与 revise_finish 的单一模型参数"""
    if set(args) != {field_name}:
        raise ValueError(f"工具参数必须且只能包含包装字段 {field_name}")
    payload = args[field_name]
    if not isinstance(payload, Mapping):
        raise ValueError(f"{field_name} 必须是对象")
    return dict(payload)


def _upsert_by_ref(
    current: list[dict[str, Any]],
    additions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """2026-08-07 用于按稳定 ref 原位替换或追加补丁项"""
    merged = [dict(item) for item in current]
    positions = {str(item["ref"]): index for index, item in enumerate(merged)}
    for item in additions:
        item_ref = str(item["ref"])
        if item_ref in positions:
            merged[positions[item_ref]] = dict(item)
        else:
            positions[item_ref] = len(merged)
            merged.append(dict(item))
    return merged


def _remove_refs(
    values: list[dict[str, Any]],
    removed_refs: set[str],
) -> list[dict[str, Any]]:
    """2026-08-07 用于从实体或事实列表删除指定稳定 ref"""
    return [dict(item) for item in values if str(item["ref"]) not in removed_refs]


def _merge_entity_patch(
    current: dict[str, Any],
    patch: EntityDirectoryPatch,
) -> dict[str, Any]:
    """2026-08-07 用于按实体类型和稳定 ref 合并目录局部补丁"""
    merged = {
        field_name: [dict(item) for item in current.get(field_name, [])]
        for field_name in _ENTITY_FIELDS
    }
    removed_refs = set(patch.remove_refs or [])
    if removed_refs:
        for field_name in _ENTITY_FIELDS:
            merged[field_name] = _remove_refs(merged[field_name], removed_refs)

    for field_name in _ENTITY_FIELDS:
        additions = getattr(patch, f"upsert_{field_name}")
        if additions is None:
            continue
        addition_payloads = [
            item.model_dump(mode="json")
            for item in additions
        ]
        addition_refs = {str(item["ref"]) for item in addition_payloads}
        for other_field in _ENTITY_FIELDS:
            if other_field != field_name:
                merged[other_field] = _remove_refs(merged[other_field], addition_refs)
        merged[field_name] = _upsert_by_ref(merged[field_name], addition_payloads)
    return merged


def _merge_chunk_patch(
    current: dict[str, Any],
    patch: ChunkFinishPatch,
) -> dict[str, Any]:
    """2026-08-07 用于按 chunk_id 与事实 ref 合并单个 chunk 补丁"""
    merged = dict(current)
    if patch.summary is not None:
        merged["summary"] = patch.summary
    if patch.metrics is not None:
        merged["metrics"] = patch.metrics.model_dump(mode="json")

    removed_refs = set(patch.remove_refs or [])
    if removed_refs:
        for field_name in _FACT_FIELDS:
            merged[field_name] = _remove_refs(list(merged.get(field_name, [])), removed_refs)

    for field_name in _FACT_FIELDS:
        additions = getattr(patch, f"upsert_{field_name}")
        if additions is None:
            continue
        addition_payloads = [
            item.model_dump(mode="json")
            for item in additions
        ]
        addition_refs = {str(item["ref"]) for item in addition_payloads}
        for other_field in _FACT_FIELDS:
            if other_field != field_name:
                merged[other_field] = _remove_refs(
                    list(merged.get(other_field, [])),
                    addition_refs,
                )
        merged[field_name] = _upsert_by_ref(
            list(merged.get(field_name, [])),
            addition_payloads,
        )
    return merged


def _merge_patch(candidate: dict[str, Any], patch: ChapterFinishPatch) -> dict[str, Any]:
    """2026-08-07 用于把 ref 局部补丁合并到当前完整 ChapterFinish"""
    merged = dict(candidate)
    if patch.chapter_summary is not None:
        merged["chapter_summary"] = patch.chapter_summary
    if patch.entities is not None:
        merged["entities"] = _merge_entity_patch(
            dict(merged.get("entities") or {}),
            patch.entities,
        )
    if patch.chunks is not None:
        chunks = [dict(chunk) for chunk in merged.get("chunks", [])]
        positions = {int(chunk["chunk_id"]): index for index, chunk in enumerate(chunks)}
        for chunk_patch in patch.chunks:
            if chunk_patch.chunk_id not in positions:
                raise ValueError(f"chunk patch 引用了不存在的 current chunk: {chunk_patch.chunk_id}")
            index = positions[chunk_patch.chunk_id]
            chunks[index] = _merge_chunk_patch(chunks[index], chunk_patch)
        merged["chunks"] = chunks
    if patch.coverage is not None:
        merged["coverage"] = [
            item.model_dump(mode="json")
            for item in patch.coverage
        ]
    return merged


def _submission_call(state: AnnotationGraphState) -> dict[str, Any]:
    """2026-08-07 用于取得当前 Agent 消息中的唯一提交工具调用"""
    last_message = state["messages"][-1]
    calls = last_message.tool_calls if isinstance(last_message, AIMessage) else []
    submissions = [call for call in calls if call.get("name") in {"finish", "revise_finish"}]
    if len(calls) != 1 or len(submissions) != 1:
        raise ValueError("finish 或 revise_finish 必须在单独一轮中唯一调用")
    return dict(submissions[0])


def _build_agent_node(
    llm: Any,
    tools: list[Any],
    *,
    ledger: AnnotationToolLedger,
    max_iterations: int,
):
    """2026-08-07 用于构建同步工具权限阶段并限制循环次数的模型节点"""

    async def agent_node(state: AnnotationGraphState) -> dict[str, Any]:
        """2026-08-07 用于执行一次绑定当前工具合同的模型调用"""
        iterations = int(state.get("iterations") or 0)
        if iterations >= max_iterations:
            return {"error": f"annotation LangGraph 内部循环达到上限 {max_iterations}"}
        ledger.set_phase(state["phase"])
        response = await llm.bind_tools(tools).ainvoke(list(state["messages"]))
        return {"messages": [response], "iterations": iterations + 1}

    return agent_node


def _route_after_agent(state: AnnotationGraphState) -> str:
    """2026-08-07 用于按开关控制的当前后文和收束阶段路由"""
    if state.get("error"):
        return "end"
    last_message = state["messages"][-1]
    calls = last_message.tool_calls if isinstance(last_message, AIMessage) else []
    names = [str(call.get("name")) for call in calls]
    phase = state["phase"]

    if phase == "current_open":
        if not calls:
            return "repair_current"
        if any(name in {"finish", "revise_finish"} for name in names):
            return "current_finalize"
        if all(name in _CURRENT_TOOL_NAMES for name in names):
            return "current_tools"
        return "protocol_error"

    if phase == "repair_current":
        return "current_finalize" if names == ["revise_finish"] else "repair_current"

    if phase == "future_open":
        if not calls:
            return "complete_candidate"
        if names == ["revise_finish"]:
            return "future_revision_finalize"
        if names and all(name == "push" for name in names):
            return "future_push_tools"
        if all(name in _FUTURE_TOOL_NAMES for name in names):
            return "future_tools"
        return "protocol_error"

    if phase == "repair_future":
        return "future_revision_finalize" if names == ["revise_finish"] else "repair_future"

    if phase == "future_finalize":
        if not calls:
            return "complete_candidate"
        if names and all(name == "push" for name in names):
            return "future_push_tools"
        return "protocol_error"

    return "end"


def _build_tools_node(
    tools: list[Any],
    *,
    ledger: AnnotationToolLedger,
):
    """2026-08-07 用于构建只执行非提交工具并同步工具权限的节点"""
    ordinary_tools = [
        candidate
        for candidate in tools
        if candidate.name not in {"finish", "revise_finish"}
    ]
    tool_node = ToolNode(ordinary_tools, handle_tool_errors=False)

    async def run_tools(state: AnnotationGraphState) -> dict[str, Any]:
        """2026-08-07 用于执行当前阶段已通过路由门禁的普通工具调用"""
        ledger.set_phase(state["phase"])
        return dict(await tool_node.ainvoke(state))

    return run_tools


def _build_phase_node(
    *,
    ledger: AnnotationToolLedger,
    phase: AnnotationPhase,
):
    """2026-08-07 用于在工具执行后显式切换 LangGraph 与账本阶段"""

    def set_phase(_state: AnnotationGraphState) -> dict[str, Any]:
        """2026-08-07 用于写入下一模型调用使用的阶段"""
        ledger.set_phase(phase)
        return {"phase": phase}

    return set_phase


def _build_repair_node(
    *,
    ledger: AnnotationToolLedger,
    future: bool,
):
    """2026-08-07 用于构建当前或后文阶段的候选修复反馈节点"""

    def repair_node(state: AnnotationGraphState) -> dict[str, Any]:
        """2026-08-07 用于要求 Agent 仅提交局部 revise_finish 修正"""
        candidate = state.get("candidate")
        if candidate is None:
            phase: AnnotationPhase = "current_open"
            message = "尚无完整候选，请先在单独一轮调用 finish 提交完整章节标注"
        else:
            phase = "repair_future" if future else "repair_current"
            message = "上一份完整候选已保留，请只调用 revise_finish 提交实际变化字段"
        ledger.set_phase(phase)
        return {"phase": phase, "messages": [SystemMessage(content=message)]}

    return repair_node


def _build_current_finalize_node(
    *,
    ledger: AnnotationToolLedger,
    validator: Callable[[ChapterFinish], None],
):
    """2026-08-07 用于校验首次 finish 或当前阶段局部修正"""

    def finalize_current(state: AnnotationGraphState) -> dict[str, Any]:
        """2026-08-07 用于保存首份有效 finish 并按后文开关决定是否结束"""
        candidate = state.get("candidate")
        revision_payloads = list(state.get("revision_payloads") or [])
        call: dict[str, Any] | None = None
        patch: ChapterFinishPatch | None = None
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
                patch = ChapterFinishPatch.model_validate(patch_payload)
                candidate = _merge_patch(candidate, patch)
            finish = ChapterFinish.model_validate(candidate)
            validator(finish)
        except Exception as exc:  # noqa: BLE001
            ledger.set_phase("repair_current")
            return {
                "candidate": candidate,
                "revision_payloads": revision_payloads,
                "phase": "repair_current",
                "messages": [
                    SystemMessage(
                        content=(
                            f"finish 校验失败: {exc}\n"
                            "候选已保留，只调用 revise_finish 提交实际变化字段"
                        )
                    )
                ],
            }

        if call is None:
            raise AnnotationProtocolError("当前阶段提交调用缺失")
        if patch is not None:
            revision_payloads.append(patch.model_dump(mode="json", exclude_unset=True))
        finish_payload = finish.model_dump(mode="json")
        if not ledger.allow_future_context:
            ledger.set_phase("completed")
            return {
                "candidate": finish_payload,
                "initial_finish": finish_payload,
                "final_finish": finish_payload,
                "revision_payloads": revision_payloads,
                "phase": "completed",
            }

        ledger.set_phase("future_open")
        return {
            "candidate": finish_payload,
            "initial_finish": finish_payload,
            "revision_payloads": revision_payloads,
            "phase": "future_open",
            "messages": [
                ToolMessage(
                    content=(
                        "当前章节完整标注已通过。future 能力现已开放；"
                        "可检索后文、修正 finish、pull 已确认案例，"
                        "确认全部允许上下文处理完毕后再 push 仍未解决案例，"
                        "无其他操作时直接回复且不要调用工具"
                    ),
                    tool_call_id=str(call["id"]),
                    name=str(call["name"]),
                )
            ],
        }

    return finalize_current


def _build_future_revision_finalize_node(
    *,
    ledger: AnnotationToolLedger,
    validator: Callable[[ChapterFinish], None],
):
    """2026-08-07 用于校验后文阶段 ref 局部修正并继续开放 future"""

    def finalize_future_revision(state: AnnotationGraphState) -> dict[str, Any]:
        """2026-08-07 用于合并有效后文修正并返回 future 阶段"""
        candidate = state.get("candidate")
        revision_payloads = list(state.get("revision_payloads") or [])
        call: dict[str, Any] | None = None
        try:
            if candidate is None:
                raise ValueError("future 阶段缺少首份有效 finish")
            call = _submission_call(state)
            if call.get("name") != "revise_finish":
                raise ValueError("future 阶段只允许 revise_finish 修改 finish")
            patch_payload = _unwrap_tool_payload(
                dict(call.get("args") or {}),
                field_name="correction",
            )
            patch = ChapterFinishPatch.model_validate(patch_payload)
            candidate = _merge_patch(candidate, patch)
            finish = ChapterFinish.model_validate(candidate)
            validator(finish)
        except Exception as exc:  # noqa: BLE001
            ledger.set_phase("repair_future")
            return {
                "candidate": candidate,
                "revision_payloads": revision_payloads,
                "phase": "repair_future",
                "messages": [
                    SystemMessage(
                        content=(
                            f"future revise_finish 校验失败: {exc}\n"
                            "必须继续调用 revise_finish 修正，不能用无工具响应绕过"
                        )
                    )
                ],
            }

        if call is None:
            raise AnnotationProtocolError("future 修正调用缺失")
        revision_payloads.append(patch.model_dump(mode="json", exclude_unset=True))
        ledger.set_phase("future_open")
        return {
            "candidate": finish.model_dump(mode="json"),
            "revision_payloads": revision_payloads,
            "phase": "future_open",
            "messages": [
                ToolMessage(
                    content="finish 修正已通过，future 工具继续开放",
                    tool_call_id=str(call["id"]),
                    name=str(call["name"]),
                )
            ],
        }

    return finalize_future_revision


def _complete_candidate(state: AnnotationGraphState) -> dict[str, Any]:
    """2026-08-07 用于把当前有效候选确定为最终 ChapterFinish"""
    candidate = state.get("candidate")
    if candidate is None:
        return {"error": "完成阶段缺少有效 ChapterFinish"}
    return {
        "final_finish": dict(candidate),
        "phase": "completed",
    }


def _protocol_error(state: AnnotationGraphState) -> dict[str, Any]:
    """2026-08-07 用于直接拒绝当前阶段禁止或混合的工具调用"""
    last_message = state["messages"][-1]
    calls = last_message.tool_calls if isinstance(last_message, AIMessage) else []
    names = [str(call.get("name")) for call in calls]
    return {"error": f"阶段 {state['phase']} 拒绝工具调用: {names}"}


def _route_after_terminal_node(state: AnnotationGraphState) -> str:
    """2026-08-07 用于在完成或错误状态下结束专用图"""
    if state.get("error") or state.get("final_finish") is not None:
        return END
    return "agent"


def build_annotation_graph(
    llm: Any,
    tools: list[Any],
    *,
    ledger: AnnotationToolLedger,
    max_iterations: int,
    current_validator: Callable[[ChapterFinish], None],
    future_validator: Callable[[ChapterFinish], None],
) -> Any:
    """2026-08-07 用于构建由 allow_future_context 控制的章节标注专用图"""
    graph = StateGraph(AnnotationGraphState)
    graph.add_node(
        "agent",
        _build_agent_node(
            llm,
            tools,
            ledger=ledger,
            max_iterations=max_iterations,
        ),
    )
    graph.add_node("current_tools", _build_tools_node(tools, ledger=ledger))
    graph.add_node("future_tools", _build_tools_node(tools, ledger=ledger))
    graph.add_node("future_push_tools", _build_tools_node(tools, ledger=ledger))
    graph.add_node(
        "set_current_open",
        _build_phase_node(ledger=ledger, phase="current_open"),
    )
    graph.add_node(
        "set_future_open",
        _build_phase_node(ledger=ledger, phase="future_open"),
    )
    graph.add_node(
        "set_future_finalize",
        _build_phase_node(ledger=ledger, phase="future_finalize"),
    )
    graph.add_node(
        "repair_current",
        _build_repair_node(ledger=ledger, future=False),
    )
    graph.add_node(
        "repair_future",
        _build_repair_node(ledger=ledger, future=True),
    )
    graph.add_node(
        "current_finalize",
        _build_current_finalize_node(
            ledger=ledger,
            validator=current_validator,
        ),
    )
    graph.add_node(
        "future_revision_finalize",
        _build_future_revision_finalize_node(
            ledger=ledger,
            validator=future_validator,
        ),
    )
    graph.add_node("complete_candidate", _complete_candidate)
    graph.add_node("protocol_error", _protocol_error)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        _route_after_agent,
        {
            "current_tools": "current_tools",
            "future_tools": "future_tools",
            "future_push_tools": "future_push_tools",
            "current_finalize": "current_finalize",
            "future_revision_finalize": "future_revision_finalize",
            "repair_current": "repair_current",
            "repair_future": "repair_future",
            "complete_candidate": "complete_candidate",
            "protocol_error": "protocol_error",
            "end": END,
        },
    )
    graph.add_edge("current_tools", "set_current_open")
    graph.add_edge("future_tools", "set_future_open")
    graph.add_edge("future_push_tools", "set_future_finalize")
    graph.add_edge("set_current_open", "agent")
    graph.add_edge("set_future_open", "agent")
    graph.add_edge("set_future_finalize", "agent")
    graph.add_edge("repair_current", "agent")
    graph.add_edge("repair_future", "agent")
    for node_name in (
        "current_finalize",
        "future_revision_finalize",
        "complete_candidate",
        "protocol_error",
    ):
        graph.add_conditional_edges(
            node_name,
            _route_after_terminal_node,
            {"agent": "agent", END: END},
        )
    return graph.compile()
