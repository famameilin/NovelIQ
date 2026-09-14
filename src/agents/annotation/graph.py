"""
章节标注逐 chunk 语义写入 LangGraph

消息链采用 messages + add_messages 累积；每次模型请求携带完整历史消息。
冻结与章节组装由程序自动执行：模型用唯一 finish_chapter 收尾后
图节点自动冻结 chunk 并完成章节，模型不需要调用完成工具。

2026-09-13 实时写入：一个模型回合可以包含多个有类型的小调用（每条只写一个完整
语义单元、写入即生效），写完全部内容后用 finish_chapter 收尾；收尾判定推迟到本回合
全部调用处理完毕之后（逐条失败只回滚该调用、不阻塞收尾），因此一次回复整体仍计
一个回合。
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import ValidationError

from .errors import AnnotationInvariantError, AnnotationStageRejection
from .tools import (
    _DOMAIN_ORDER,
    _WRITE_TOOL_NAMES,
    AnnotationToolLedger,
    translate_write_validation_error,
)

if TYPE_CHECKING:
    from src.agents.audit.observer import AgentTurnObserver
    from src.agents.stream import AgentStream

# 2026-08-14 D1：无 continuity_open 阶段，chunk_open -> completed 两态
AnnotationPhase = Literal["chunk_open", "completed"]

# 2026-09-05 剩余轮次（含本轮）进入该窗口即向本次请求追加收尾提醒
TURN_BUDGET_REMINDER_WINDOW = 3

# 2026-09-11 章内并行：区分"未传 completion_hint"（用缺内容提醒）与显式传 None（无提醒）
_HINT_SENTINEL = object()


def _turn_budget_reminder(remaining: int) -> str:
    """2026-09-05 用于构造临近内部循环上限时模型可见的收尾提醒

    2026-09-05 第3章死锁：模型空转 15 轮 40 次检索 0 写入后撞硬顶，
    全程看不到轮次预算。此提醒为纯消息注入（不改工具开放与路由），
    只对本次请求生效、不写入状态消息链，避免多轮提醒在历史中堆积。

    2026-09-13 末轮点名收尾：run c80105cc 第 4 章实测——末轮文案只说
    "提交全部已确认内容"，模型把写入排在前面、finish_chunk 留给"下一轮"，该轮
    结束后撞硬顶、整章作废（第 15 轮思考里计划含 finish_chunk，实际只发出 3 个
    写入调用）。末轮必须点名唯一的收尾动作，并说明收尾可与写入同批提交。
    2026-09-14 收尾工具更名 finish_chapter（冻结单位本就是整章）。
    """
    if remaining <= 1:
        return (
            "【轮次预算】本轮是内部循环的最后一轮：写入与收尾放在同一批次提交，"
            "并在本批次里调用 finish_chapter() ——收尾判定在本批全部调用处理完后执行；"
            "本轮结束仍未收尾则本章作废，不要再发起新的检索。"
        )
    return (
        f"【轮次预算】剩余 {remaining} 轮（含本轮）将触发内部循环上限："
        "请尽快提交已确认内容，把剩余轮次留给写入与 finish_chapter() 收尾，"
        "不要再用新检索消耗轮次。"
    )


# 2026-09-13 尚无内容领域对应的补齐工具
_MISSING_CONTENT_TOOL_HINTS = {
    "entities": "write_entity（登记本章出现的实体）",
    "metrics": "write_metrics（摘要、叙事指标与段落情绪标签，必填）",
    "events": "write_event（根/子事件与参与者，确实没有事件可跳过）",
    "relations": "write_relation（本章确实没有关系可跳过）",
    "dialogues": "write_dialogue（按候选表逐条判定，确实没有可跳过）",
}


def _missing_domains_reminder(missing: list[str]) -> str | None:
    """2026-09-13 用于构造无工具回复重发前的"还没收尾"提醒

    写入即生效，收尾由唯一 finish_chapter 表达：纯文本汇报既不是写入也不是收尾，
    调用层把无工具回复视同调用故障重发，此提醒只注入重发请求（不写入状态消息链、
    不改工具开放与路由），把"还缺什么内容、怎么收尾"直接交给模型。

    2026-09-13 写者面全放开：五个写入工具从首轮起全部在工具面上，缺哪个域就报
    哪个域的补齐工具，不再有"实体未写、其余领域工具随后解锁"的分支。
    """
    ordered = [domain for domain in _DOMAIN_ORDER if domain in missing]
    head = "【收尾提醒】本章还没收尾（纯文本汇报不算写入，也不是收尾）："
    tail = "。确认写完后调用 finish_chapter() 收尾，本章才冻结；确实为空的领域直接收尾即可。"
    if not ordered:
        return f"{head}请确认已写完并调用 finish_chapter() 收尾{tail}"
    detail = "、".join(f"{domain}（{_MISSING_CONTENT_TOOL_HINTS[domain]}）" for domain in ordered)
    return f"{head}尚无内容的领域：{detail}{tail}"


def _index_ranges(values: list[int]) -> str:
    """2026-09-14 用于把候选编号列表压成区间文本（1,3,4,5,9 → "1,3-5,9"）"""
    if not values:
        return ""
    parts: list[str] = []
    start = prev = values[0]
    for value in values[1:]:
        if value == prev + 1:
            prev = value
            continue
        parts.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = value
    parts.append(str(start) if start == prev else f"{start}-{prev}")
    return ",".join(parts)


def _progress_block(ledger: AnnotationToolLedger, remaining_turns: int, max_iterations: int) -> str:
    """2026-09-14 构造写者面每回合注入的【进度账本】（用户裁决：每回合注入最新进展）

    块内只放**动态状态**（域账本现值+剩余回合）；"已判不重扫、判完即写"等处理规则
    是静态行为合同，2026-09-14 用户裁决上提 SYSTEM_PROMPT。与收尾提醒同款：只对当次
    请求生效、不写入状态消息链；案例链不注入（09-11 "不注入案例"裁决），只覆盖五个
    写入域。
    """
    lines = [
        "【进度账本】本轮时刻的本章已写入状态，由系统注入。",
        f"剩余回合 {remaining_turns}/{max_iterations}（含本轮）。",
    ]
    entities = ledger.entity_ledger()
    if entities:
        rendered = []
        for row in entities:
            extras = [f"n={row['n']}"]
            if row.get("tags"):
                extras.append("标签:" + "、".join(row["tags"]))
            if row.get("aliases"):
                extras.append("别名:" + "、".join(row["aliases"]))
            rendered.append(f"{row['el']}={row['name']}(" + "；".join(extras) + ")")
        lines.append(f"实体({len(entities)})：" + "；".join(rendered))
    else:
        lines.append("实体：未写入")
    relations = ledger.relation_ledger()
    if relations:
        lines.append(f"关系({len(relations)})：" + "；".join(relations))
    else:
        lines.append("关系：未写入")
    trees = ledger.event_ledger()
    if trees:
        parts = []
        for tree_key, entry in trees.items():
            flags = f"伏笔={str(bool(entry['foreshadowing'])).lower()}"
            if entry.get("confidence"):
                flags += f"·confidence={entry['confidence']}"
            children = "，".join(f"{child} {child_type}" for child, child_type in entry["children"].items()) or "无子"
            parts.append(f'{tree_key}="{entry["root"]}"({flags}；children: {children}；主链尾 {entry["trunk_tail"]})')
        lines.append(f"事件树({len(trees)})：" + "；".join(parts))
    else:
        lines.append("事件树：未写入")
    dialogue = ledger.dialogue_ledger()
    pending = _index_ranges(dialogue["pending"]) or "无"
    judged_line = f"对话：已判定 {dialogue['written']}/{dialogue['total']}；未判定编号：{pending}"
    if dialogue["judged"]:
        ordered = sorted(dialogue["judged"].items(), key=lambda kv: int(kv[0]))
        verdicts = "，".join(f"{idx}={value}" for idx, value in ordered)
        judged_line += f"；已判定值：{verdicts}"
    lines.append(judged_line)
    lines.append("指标：已写入" if ledger.metrics_payload is not None else "指标：未写入")
    return "\n".join(lines)


class AnnotationGraphState(TypedDict):
    """2026-08-10 用于保存逐 chunk 工具循环的累积消息链"""

    messages: Annotated[list[BaseMessage], add_messages]
    phase: AnnotationPhase
    iterations: int
    error: str | None


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
    inject_progress: bool = False,
):
    """2026-08-10 用于构建同步系统阶段并限制循环次数的模型节点

    2026-09-11 章内并行：completion_hint 显式传入（含 None）即按传入使用，缺省
    保持收尾提醒；require_tool_call=False 供读者面使用——读者没有写入工具，
    无工具回复是"上报完毕"的正常完成信号（§8.5），不得按调用故障重发。
    2026-09-14 inject_progress=True（仅写者面）时每次请求尾部注入【进度账本】：
    服务端不重放思考，模型看不到自己上轮的判定，当前态由系统逐回合直给。
    """

    if completion_hint is _HINT_SENTINEL:

        def completion_hint() -> str | None:
            """2026-09-13 无工具回复重发前按账本当前尚无内容的领域生成一次性提醒"""
            return _missing_domains_reminder(ledger.missing_content_domains())

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
        if inject_progress:
            request_messages.append(HumanMessage(content=_progress_block(ledger, remaining_turns, max_iterations)))
        if remaining_turns <= TURN_BUDGET_REMINDER_WINDOW:
            request_messages.append(HumanMessage(content=_turn_budget_reminder(remaining_turns)))

        context_summary = {
            **ledger.context_summary(),
            "allowed_tool_names": [candidate.name for candidate in tools],
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
                llm.bind_tools(tools),
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

    2026-09-12 参数绑定发生在 langchain 工具 schema 层（先于函数体）；
    2026-09-13 实时写入后该层的 pydantic 失败统一翻成结构化拒绝回执
    （record/field/code/expected），只指向出错的那一条记录。
    """
    name = str(call.get("name"))
    candidate = tool_map.get(name)
    if candidate is None:
        raise ValueError(f"未知 annotation 工具: {name}")
    args = dict(call.get("args") or {})
    try:
        result = await candidate.ainvoke(args)
    except ValidationError as exc:
        if name in _WRITE_TOOL_NAMES:
            raise translate_write_validation_error(name, args, exc) from None
        raise
    return str(result)


def _failed_receipt(name: str, error: str | BaseException) -> str:
    """2026-08-10 用于构造单个调用失败时模型可见的独立回执

    2026-09-13：结构化拒绝（AnnotationStageRejection）只回 record/field/code/
    expected 与可自纠说明，不重复整份合同。
    """
    if isinstance(error, AnnotationStageRejection):
        return json.dumps(error.receipt(), ensure_ascii=False)
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
    """2026-08-10 用于构建逐调用独立提交且互不回滚的工具节点

    2026-09-13 实时写入：一个回合的多个调用串行处理、共享账本、写入即生效；
    finish_chapter 的收尾判定推迟到本回合全部调用处理完再执行，因此
    "同轮多个小调用 + 一个收尾声明"整体只计一个模型回合。失败只影响该调用自己，
    不影响同回合其他调用、也不阻塞收尾（收尾判定见 _settle_chapter_finish）。
    """

    async def tool_batch(state: AnnotationGraphState) -> dict[str, Any]:
        """2026-09-13 用于独立串行执行本回合全部小调用并按单次调用边界回滚"""

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
        allowed_tool_names = frozenset(candidate.name for candidate in tools)
        protocol_error = _tool_batch_protocol_error(
            calls,
            allowed_tool_names=allowed_tool_names,
        )
        # 每个调用一条 entry：call/序号/内容（finish_chapter 先占位，批次末尾回填判定结果）
        rendered: list[dict[str, Any]] = [
            {"call": call, "index": call_index, "content": None}
            for call_index, call in enumerate(calls)
        ]

        async def _append_failed_call(
            entry: dict[str, Any],
            call: dict[str, Any],
            error_text: str,
        ) -> None:
            """2026-08-30 用于把协议或顺序错误作为独立失败回执和审计记录返回模型"""
            name = str(call.get("name"))
            result = _failed_receipt(name, error_text)
            entry["content"] = result
            started_ns = time.perf_counter_ns()
            if observer is not None:
                observer.record_tool_call(
                    call_index=entry["index"],
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

        if protocol_error is not None:
            ledger.errors.append(protocol_error)
            for entry in rendered:
                await _append_failed_call(entry, entry["call"], protocol_error)
            if observer is not None:
                observer.close_turn()
            return {"messages": _tool_messages(rendered), "phase": ledger.phase}
        for entry in rendered:
            call = entry["call"]
            name = str(call.get("name"))
            if call.get("truncated"):
                error_text = _truncated_error(name)
                await _append_failed_call(entry, call, error_text)
                continue
            if name == "finish_chapter":
                # 收尾声明：校验与冻结推迟到本回合全部调用处理完之后
                # （逐条失败只回滚该调用、不阻塞收尾），因此"同轮多个小调用 + 收尾"仍计一个回合
                entry["started_ns"] = time.perf_counter_ns()
                entry["content"] = await _invoke_tool(tool_map, call)
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
                result = _failed_receipt(name, exc)
                status = "error"
                error = error_text
                receipt = json.loads(result)
            tool_duration_ms = max(0, round((time.perf_counter_ns() - started_ns) / 1_000_000))
            entry["content"] = result
            if observer is not None:
                observer.record_tool_call(
                    call_index=entry["index"],
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
        await _settle_chapter_finish(
            ledger,
            rendered,
            observer=observer,
            emit_tool_status=_emit_tool_status,
        )
        if observer is not None:
            observer.close_turn()
        return {"messages": _tool_messages(rendered), "phase": ledger.phase}

    tool_map = {candidate.name: candidate for candidate in tools}
    return tool_batch


def _tool_messages(rendered: list[dict[str, Any]]) -> list[ToolMessage]:
    """2026-09-13 用于按调用顺序把回执渲染成 ToolMessage（含失败回执与延迟判定的收尾回执）"""
    messages: list[ToolMessage] = []
    for entry in rendered:
        call = entry["call"]
        messages.append(
            ToolMessage(
                content=str(entry.get("content") or ""),
                tool_call_id=str(call["id"]),
                name=str(call.get("name")),
            )
        )
    return messages


async def _settle_chapter_finish(
    ledger: AnnotationToolLedger,
    rendered: list[dict[str, Any]],
    *,
    observer: AgentTurnObserver | None,
    emit_tool_status: Any,
) -> None:
    """2026-09-13 用于在本回合全部调用处理完后执行 finish_chapter 收尾判定

    写入是实时的、不需要结算：本回合的逐条失败各自在调用点已回执，收尾只管
    按已写入内容补默认判定、校验并构造 ready_chunk（构造失败整体回滚，已写入记录保留）。
    """
    for entry in rendered:
        call = entry["call"]
        if str(call.get("name")) != "finish_chapter" or entry.get("content") is None:
            continue
        started_ns = entry.get("started_ns") or time.perf_counter_ns()
        try:
            receipt = ledger.finish_chapter()
            content = json.dumps(receipt, ensure_ascii=False)
            status: str = "success"
            error: str | None = None
        except AnnotationInvariantError:
            if observer is not None:
                observer.close_turn()
            raise
        except Exception as exc:
            ledger.errors.append(str(exc))
            content = _failed_receipt("finish_chapter", exc)
            status = "error"
            error = str(exc)
        entry["content"] = content
        if observer is not None:
            observer.record_tool_call(
                call_index=entry["index"],
                tool_name="finish_chapter",
                request_args=dict(call.get("args") or {}),
                raw_args=(str(call.get("raw_args")) if call.get("raw_args") is not None else None),
                response=json.loads(content),
                receipt=json.loads(content),
                status=status,
                error=error,
                tool_duration_ms=max(0, round((time.perf_counter_ns() - started_ns) / 1_000_000)),
                started_ns=started_ns,
            )
        if status == "success":
            await emit_tool_status("finish_chapter", "success", content)
        else:
            await emit_tool_status("finish_chapter", "error", error or "")


def _build_auto_finalize_node(
    ledger: AnnotationToolLedger,
    *,
    stream: AgentStream | None = None,
    observer: AgentTurnObserver | None = None,
):
    """2026-09-13 用于在收尾声明后自动冻结 chunk 并完成章节"""

    async def auto_finalize(state: AnnotationGraphState) -> dict[str, Any]:
        """2026-09-13 用于在 finish_chapter 收尾后冻结 chunk 并完成章节"""
        if ledger.phase != "chunk_open":
            return {"phase": ledger.phase}
        if not ledger.chapter_finished:
            return {"phase": ledger.phase}
        try:
            if stream is not None:
                await stream.tool_call_started("auto_freeze_chapter")
            ledger.complete_active_chunk()
            if stream is not None:
                await stream.tool_call_succeeded("auto_freeze_chapter", "chunk frozen")
                await stream.tool_call_started("auto_assemble_chapter")
            ledger.finish()
            if stream is not None:
                await stream.tool_call_succeeded("auto_assemble_chapter", "chapter completed")
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
    """2026-08-10 用于构建逐 chunk 领域写入和章节自动完成状态机（消息链累积）

    2026-09-14 写者面每回合注入【进度账本】（inject_progress）；读者图不开。"""
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
            inject_progress=True,
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
