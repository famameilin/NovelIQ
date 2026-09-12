"""
章节标注逐 chunk 语义写入 LangGraph

消息链采用 messages + add_messages 累积；每次模型请求携带完整历史消息。
complete_chunk 与 finish_chapter 由程序自动执行：五个写入工具覆盖六领域后
图节点自动冻结 chunk 并完成章节，模型不需要调用完成工具。
"""

from __future__ import annotations

import json
import time
from copy import deepcopy
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import ValidationError

from .errors import AnnotationInvariantError
from .tools import AnnotationToolLedger, translate_event_validation_error

if TYPE_CHECKING:
    from src.agents.audit.observer import AgentTurnObserver
    from src.agents.stream import AgentStream

# 2026-08-14 D1：无 continuity_open 阶段，chunk_open -> completed 两态
AnnotationPhase = Literal["chunk_open", "completed"]

_DOMAIN_NAMES = (
    "metrics",
    "entities",
    "character_observations",
    "dialogues",
    "events",
    "relations",
)
_DOMAIN_NAMES_SET = frozenset(_DOMAIN_NAMES)

_FORMAL_WRITE_ORDER = (
    ("entities", "write_entities"),
    ("metrics", "write_metrics"),
    ("events", "write_event"),
    ("relations", "write_relations"),
    ("dialogues", "write_dialogues"),
)
_FORMAL_WRITE_TOOL_NAMES = frozenset(tool_name for _domain, tool_name in _FORMAL_WRITE_ORDER)
_FORMAL_WRITE_DEPENDENCIES = {
    "entities": frozenset(),
    "metrics": frozenset(),
    "events": frozenset({"entities"}),
    "relations": frozenset({"entities"}),
    "dialogues": frozenset({"entities"}),
}

# 2026-09-05 剩余轮次（含本轮）进入该窗口即向本次请求追加收尾提醒
TURN_BUDGET_REMINDER_WINDOW = 3

# 2026-09-11 章内并行：区分"未传 completion_hint"（用六域缺域提醒）与显式传 None（无提醒）
_HINT_SENTINEL = object()


def _turn_budget_reminder(remaining: int) -> str:
    """2026-09-05 用于构造临近内部循环上限时模型可见的收尾提醒

    2026-09-05 第3章死锁：模型空转 15 轮 40 次检索 0 写入后撞硬顶，
    全程看不到轮次预算。此提醒为纯消息注入（不改工具开放与路由），
    只对本次请求生效、不写入状态消息链，避免多轮提醒在历史中堆积。
    """
    if remaining <= 1:
        return (
            "【轮次预算】本轮是内部循环的最后一轮：请立即用写入工具提交全部已确认内容，"
            "不要再发起新的检索。"
        )
    return (
        f"【轮次预算】剩余 {remaining} 轮（含本轮）将触发内部循环上限："
        "请尽快提交已确认内容，把剩余轮次留给写入收尾，不要再用新检索消耗轮次。"
    )


# 2026-09-08 六域回执对应的补齐工具与空提交写法
_MISSING_DOMAIN_TOOL_HINTS = {
    "entities": "write_entities（无实体时提交 {\"entities\": []}）",
    "metrics": "write_metrics",
    "events": "write_event（无事件时提交 {\"description\": null, \"finalize_events\": true}）",
    "character_observations": "write_event（随事件域一并完成，无需单独提交）",
    "relations": "write_relations（无关系变化时提交 {\"relations\": []}）",
    "dialogues": "write_dialogues（无对话时提交 {\"dialogues\": []}）",
}


def _missing_domains_reminder(missing: list[str], *, unlocked_domains: frozenset[str]) -> str | None:
    """2026-09-08 用于构造无工具回复重发前的缺域补齐提醒

    第13章死锁：模型写完自认为"已完成"的领域后改用纯文本汇报收尾，
    调用层把无工具回复视同调用故障原样重发，模型看不到任何缺域信息、
    必然继续汇报，三次耗尽即章失败。此提醒只注入重发请求（不写入状态
    消息链、不改工具开放与路由），把"还缺什么、怎么补"直接交给模型。

    2026-09-12 只提当前已解锁的缺域：未解锁域的补齐工具不在本轮工具面上，
    报工具名即越界引用（工具相关内容只在工具暴露时进入上下文）。
    """
    ordered = [
        domain
        for domain, _tool_name in _FORMAL_WRITE_ORDER
        if domain in missing and domain in unlocked_domains
    ]
    ordered += [
        domain
        for domain in missing
        if domain not in ordered and domain in unlocked_domains
    ]
    if not ordered:
        return None
    detail = "、".join(f"{domain}（{_MISSING_DOMAIN_TOOL_HINTS[domain]}）" for domain in ordered)
    head = "【缺域提醒】当前 chunk 仍有领域未提交回执，纯文本汇报不算写入："
    tail = "。全部领域回执齐全后 chunk 会自动冻结完成。"
    if "entities" in ordered:
        return f"{head}{detail}。write_entities 是其余写入工具的解锁前提，请先补齐它{tail}"
    return f"{head}{detail}。请立即调用对应写入工具补齐{tail}"


class AnnotationGraphState(TypedDict):
    """2026-08-10 用于保存逐 chunk 工具循环的累积消息链"""

    messages: Annotated[list[BaseMessage], add_messages]
    phase: AnnotationPhase
    iterations: int
    error: str | None


def _active_write_tools(ledger: AnnotationToolLedger) -> tuple[str, ...]:
    """2026-09-03 用于按依赖解锁正式写入工具：解锁后只追加进列表，已写入不移除、不设每轮上限"""
    return tuple(
        tool_name
        for domain, tool_name in _FORMAL_WRITE_ORDER
        if _FORMAL_WRITE_DEPENDENCIES[domain] <= ledger.domain_receipts
    )


def _active_write_tool(ledger: AnnotationToolLedger) -> str | None:
    """2026-08-30 用于返回当前开放窗口中的首个待写工具供审计展示"""
    active_write_tools = _active_write_tools(ledger)
    return active_write_tools[0] if active_write_tools else None


def _unlocked_write_domains(ledger: AnnotationToolLedger) -> frozenset[str]:
    """2026-09-12 用于返回补齐工具已出现在本轮工具面上的领域

    缺域提醒只提这些域（见 _missing_domains_reminder）。character_observations
    随事件域经 write_event 一并写入，跟随 events 解锁。
    """
    unlocked = {
        domain
        for domain, _tool_name in _FORMAL_WRITE_ORDER
        if _FORMAL_WRITE_DEPENDENCIES[domain] <= ledger.domain_receipts
    }
    if "events" in unlocked:
        unlocked.add("character_observations")
    return frozenset(unlocked)


def _tools_for_turn(tools: list[Any], ledger: AnnotationToolLedger) -> list[Any]:
    """2026-09-03 用于保留非正式工具并暴露依赖已解锁的正式写入工具（只追加不替换）"""
    tools_by_name = {candidate.name: candidate for candidate in tools}
    active_write_tools = [
        tools_by_name[name] for name in _active_write_tools(ledger) if name in tools_by_name
    ]
    nonformal_tools = [candidate for candidate in tools if candidate.name not in _FORMAL_WRITE_TOOL_NAMES]
    return [*active_write_tools, *nonformal_tools]


def _tool_batch_protocol_error(
    calls: list[dict[str, Any]],
    *,
    allowed_tool_names: frozenset[str],
) -> str | None:
    """2026-08-30 用于校验模型回合只调用本轮开放的工具"""
    if not calls:
        return "每个模型回合必须调用工具"
    unavailable = [str(call.get("name")) for call in calls if str(call.get("name")) not in allowed_tool_names]
    if unavailable:
        return f"本轮未开放工具: {unavailable}"
    return None


def _build_agent_node(
    llm: Any,
    tools: list[Any],
    *,
    ledger: AnnotationToolLedger,
    max_iterations: int,
    stream: AgentStream | None = None,
    observer: AgentTurnObserver | None = None,
    retries: int | None = None,
    completion_hint: Any = _HINT_SENTINEL,
    require_tool_call: bool = True,
):
    """2026-08-10 用于构建同步系统阶段并限制循环次数的模型节点

    2026-09-11 章内并行：completion_hint 显式传入（含 None）即按传入使用，缺省
    保持六域缺域提醒；require_tool_call=False 供读者面使用——读者没有写入工具，
    无工具回复是"上报完毕"的正常完成信号（§8.5），不得按调用故障重发。
    """

    if completion_hint is _HINT_SENTINEL:

        def completion_hint() -> str | None:
            """2026-09-08 无工具回复重发前按账本当前缺域生成一次性提醒"""
            missing = [
                domain for domain in _DOMAIN_NAMES if domain not in ledger.domain_receipts
            ]
            if not missing:
                return None
            return _missing_domains_reminder(missing, unlocked_domains=_unlocked_write_domains(ledger))

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
        remaining_turns = max_iterations - iterations
        if remaining_turns <= TURN_BUDGET_REMINDER_WINDOW:
            request_messages.append(HumanMessage(content=_turn_budget_reminder(remaining_turns)))

        active_write_tool = _active_write_tool(ledger)
        active_write_tools = _active_write_tools(ledger)
        turn_tools = _tools_for_turn(tools, ledger)
        context_summary = {
            **ledger.context_summary(),
            "active_write_tool": active_write_tool,
            "active_write_tools": list(active_write_tools),
            "allowed_tool_names": [candidate.name for candidate in turn_tools],
        }

        def on_turn_started(provider_request: dict[str, Any], started_ns: int) -> None:
            """2026-08-30 用于在物理 Provider 请求发送前写入独立审计行"""
            if observer is None:
                return
            observer.begin_provider_turn(
                context_summary=context_summary,
                request_messages=request_messages,
                provider_request=provider_request,
                started_ns=started_ns,
            )

        def on_turn_complete(message: AIMessage, timing: Any) -> None:
            """2026-08-30 用于收口成功的物理 Provider 请求审计"""
            if observer is None:
                return
            observer.complete_provider_turn(response_message=message, timing=timing)

        def on_turn_failed(error: str, timing: Any, message: AIMessage | None) -> None:
            """2026-08-30 用于收口断流超时和无工具回复的物理 Provider 请求审计"""
            if observer is None:
                return
            observer.fail_provider_turn(error=error, timing=timing, response_message=message)

        try:
            response = await run_model_call(
                llm.bind_tools(turn_tools),
                request_messages,
                stream,
                on_turn_complete=on_turn_complete,
                on_turn_started=on_turn_started,
                on_turn_failed=on_turn_failed,
                total_attempts=retries,
                completion_hint=completion_hint,
                require_tool_call=require_tool_call,
            )
        except Exception:
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
    """2026-08-10 用于区分普通工具批次和错误收口

    2026-08-22 无工具回复改由调用层（run_model_call）拦截重发，
    到达此处的响应必含工具调用，路由只剩错误收口与工具批次两条分支。
    """
    if state.get("error"):
        return "end"
    return "tool_batch"


async def _invoke_tool(tool_map: dict[str, Any], call: dict[str, Any]) -> str:
    """2026-08-07 用于按模型工具调用执行同步或异步 LangChain 工具

    2026-09-12 write_event 的参数绑定发生在 langchain 工具 schema 层（先于
    函数体），该层的 pydantic 失败同样翻译成中文规则报错；函数体层的根级
    校验由 write_event 自己兜底。
    """
    name = str(call.get("name"))
    candidate = tool_map.get(name)
    if candidate is None:
        raise ValueError(f"未知 annotation 工具: {name}")
    try:
        result = await candidate.ainvoke(dict(call.get("args") or {}))
    except ValidationError as exc:
        if name == "write_event":
            raise translate_event_validation_error(exc) from None
        raise
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


_CREATE_EVENT_PATCH_HINT = (
    "；本次提交已缓存为草稿，重调 write_event 只需 patches=[[字段路径, 新值], ...] "
    "修正上述路径对应字段（路径见报错，已正确的部分无需重发），"
    "不带 patches 则表示整体重交并取代草稿"
)


def _stash_write_event_draft(ledger: AnnotationToolLedger, call: dict[str, Any], error_text: str) -> str:
    """2026-09-11 用于把校验失败的 write_event 参数缓存为草稿并附增量修正提示

    补丁式重调（args 含 patches）失败时草稿已由 merge_event_patches 更新为合并结果，
    不得用本次的 patches 参数覆盖草稿。
    """
    args = call.get("args")
    if isinstance(args, dict) and "patches" not in args:
        ledger.stash_event_draft(deepcopy(args))
    return error_text + _CREATE_EVENT_PATCH_HINT


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
        """2026-08-30 用于独立串行执行至多两种正式写入并按单次调用边界回滚"""

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
        allowed_tool_names = frozenset(candidate.name for candidate in _tools_for_turn(tools, ledger))
        protocol_error = _tool_batch_protocol_error(
            calls,
            allowed_tool_names=allowed_tool_names,
        )

        async def _append_failed_call(call_index: int, call: dict[str, Any], error_text: str) -> None:
            """2026-08-30 用于把协议或顺序错误作为独立失败回执和审计记录返回模型"""
            name = str(call.get("name"))
            result = _failed_receipt(name, error_text)
            started_ns = time.perf_counter_ns()
            if observer is not None:
                observer.record_tool_call(
                    call_index=call_index,
                    tool_name=name,
                    request_args=dict(call.get("args") or {}),
                    raw_args=(str(call.get("raw_args")) if call.get("raw_args") is not None else None),
                    response=json.loads(result),
                    receipt=json.loads(result),
                    status="error",
                    error=error_text,
                    tool_duration_ms=0,
                    started_ns=started_ns,
                )
            await _emit_tool_status(name, "error", error_text)
            messages.append(
                ToolMessage(
                    content=result,
                    tool_call_id=str(call["id"]),
                    name=name,
                )
            )

        if protocol_error is not None:
            ledger.errors.append(protocol_error)
            for call_index, call in enumerate(calls):
                await _append_failed_call(call_index, call, protocol_error)
            if observer is not None:
                observer.close_turn()
            return {"messages": messages, "phase": ledger.phase}
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
                        raw_args=(str(call.get("raw_args")) if call.get("raw_args") is not None else None),
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
            graph_snapshot = ledger.graph.snapshot() if ledger.graph is not None else None
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
            except Exception as exc:
                ledger.restore(ledger_snapshot)
                if graph_snapshot is not None and ledger.graph is not None:
                    ledger.graph.restore(graph_snapshot)
                ledger.errors.append(str(exc))
                error_text = str(exc)
                if name == "write_event":
                    error_text = _stash_write_event_draft(ledger, call, error_text)
                result = _failed_receipt(name, error_text)
                status = "error"
                error = error_text
                receipt = json.loads(result)
            tool_duration_ms = max(0, round((time.perf_counter_ns() - started_ns) / 1_000_000))
            if observer is not None:
                observer.record_tool_call(
                    call_index=call_index,
                    tool_name=name,
                    request_args=dict(call.get("args") or {}),
                    raw_args=(str(call.get("raw_args")) if call.get("raw_args") is not None else None),
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
    """2026-08-30 用于六个内部数据领域就绪后自动完成章节"""

    async def auto_finalize(state: AnnotationGraphState) -> dict[str, Any]:
        """2026-08-30 用于在六领域回执齐全时冻结 chunk 并完成章节"""
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
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        _route_after_agent,
        {
            "tool_batch": "tool_batch",
            "end": END,
        },
    )
    graph.add_edge("tool_batch", "auto_finalize")
    graph.add_conditional_edges(
        "auto_finalize",
        _route_after_work,
        {"agent": "agent", END: END},
    )
    return graph.compile()


def _route_after_reader_agent(state: AnnotationGraphState) -> str:
    """2026-09-11 用于读者循环路由：错误收口、工具批次、无工具回复即上报完毕（§8.5）"""
    if state.get("error"):
        return "end"
    if not _tool_calls(state):
        return "end"
    return "tool_batch"


def build_reader_graph(
    llm: Any,
    tools: list[Any],
    *,
    ledger: AnnotationToolLedger,
    max_iterations: int,
    stream: AgentStream | None = None,
    observer: AgentTurnObserver | None = None,
    retries: int | None = None,
) -> Any:
    """2026-09-11 章内并行（§6/§8.1 Phase A）：构建读者循环状态机

    读者只有检索与 send_message，无写入工具、无领域冻结：轮次预算提醒保留
    （防单块空转），缺域提醒移除（读者没有六域合同），无工具回复即视为该读者
    上报完毕正常收束。
    """
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
            completion_hint=None,
            require_tool_call=False,
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
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        _route_after_reader_agent,
        {
            "tool_batch": "tool_batch",
            "end": END,
        },
    )
    graph.add_edge("tool_batch", "agent")
    return graph.compile()


__all__ = ["AnnotationGraphState", "build_annotation_graph", "build_reader_graph"]
