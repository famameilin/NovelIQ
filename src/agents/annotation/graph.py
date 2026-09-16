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
from typing import TYPE_CHECKING, Annotated, Any, Literal, NotRequired, TypedDict, get_args

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


def _missing_domains_reminder(missing: list[str], *, program_mode: bool = False) -> str | None:
    """2026-09-13 用于构造无工具回复重发前的"还没收尾"提醒

    写入即生效，收尾由唯一 finish_chapter 表达：纯文本汇报既不是写入也不是收尾，
    调用层把无工具回复视同调用故障重发，此提醒只注入重发请求（不写入状态消息链、
    不改工具开放与路由），把"还缺什么内容、怎么收尾"直接交给模型。

    2026-09-13 写者面全放开：五个写入工具从首轮起全部在工具面上，缺哪个域就报
    哪个域的补齐工具，不再有"实体未写、其余领域工具随后解锁"的分支。
    2026-09-15 程序面：写者只暴露 execute_code，提醒需要点明"写成程序提交"。
    """
    ordered = [domain for domain in _DOMAIN_ORDER if domain in missing]
    head = "【收尾提醒】本章还没收尾（纯文本汇报不算写入，也不是收尾）："
    tail = "。确认写完后调用 finish_chapter() 收尾，本章才冻结；确实为空的领域直接收尾即可。"
    if program_mode:
        head = "【收尾提醒】本章还没收尾（纯文本汇报不算写入，也不是收尾；工具调用要写进 execute_code 的程序提交）："
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
    """2026-09-14 构造写者面每回合注入的【进度账本】（每回合注入最新进展）

    块内只放**动态状态**（域账本现值+剩余回合）；"已判不重扫、判完即写"等处理规则
    是静态行为合同，2026-09-14 上提 SYSTEM_PROMPT。与收尾提醒同款：只对当次
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
    # 2026-09-16 块代理面：轮次上限按"会话自然收束"处理（局部标注是内存对象、
    # 构造即校验，撞上限只是停止会话，不是失败）；写者/读者面不置位、行为不变
    halted: NotRequired[bool]


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
    bind_tools: list[Any] | None = None,
    program_mode: bool = False,
    stop_at_iteration_limit: bool = False,
):
    """2026-08-10 用于构建同步系统阶段并限制循环次数的模型节点

    2026-09-11 章内并行：completion_hint 显式传入（含 None）即按传入使用，缺省
    保持收尾提醒；require_tool_call=False 供读者面使用——读者没有写入工具，
    无工具回复是"上报完毕"的正常完成信号（§8.5），不得按调用故障重发。
    2026-09-14 inject_progress=True（仅写者面）时每次请求尾部注入【进度账本】：
    服务端不重放思考，模型看不到自己上轮的判定，当前态由系统逐回合直给。
    2026-09-15 bind_tools：绑定面与执行面拆开——程序面只把 execute_code 交给模型
    （广告面也同步只报它），分发字典仍是完整工具表。
    """

    advertised = list(bind_tools) if bind_tools is not None else list(tools)

    if completion_hint is _HINT_SENTINEL:

        def completion_hint() -> str | None:
            """2026-09-13 无工具回复重发前按账本当前尚无内容的领域生成一次性提醒"""
            return _missing_domains_reminder(ledger.missing_content_domains(), program_mode=program_mode)

    async def agent_node(state: AnnotationGraphState) -> dict[str, Any]:
        """2026-08-10 用于执行一次绑定语义工具合同的模型调用"""
        iterations = int(state.get("iterations") or 0)
        if iterations >= max_iterations:
            if stop_at_iteration_limit:
                # 2026-09-16 块代理面：撞轮次上限按会话自然收束处理（局部标注构造即
                # 校验，已构造的内容就是产出），不按失败上报、不新增升级分支
                return {"halted": True}
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
            "allowed_tool_names": [candidate.name for candidate in advertised],
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
                llm.bind_tools(advertised),
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


_NULLISH_ARG_WORDS = frozenset({"null", "none", "nil", ""})


def _coerce_nullish_write_args(tool: Any, args: dict[str, Any]) -> dict[str, Any]:
    """2026-09-14 null 字面串统一容错（run a8c29ec8 实锤：speaker="null" 白烧 3 个调用/回合）

    模型惯犯把 JSON null 写成字符串 "null"。写入类工具的参数里，凡 schema 声明可空
    （Optional）的参数，null 类字面串一律按留空读取；必填参数不改，交给账本校验/类型
    报错——那里 null 不是合法的"未提供"。转换放在生产调用入口而不是工具签名：
    @tool 保留真实类型（enum/union）但剥掉 Annotated 的 BeforeValidator（09-14 tone 实测）。
    """
    schema = getattr(tool, "args_schema", None)
    fields = getattr(schema, "model_fields", None) or {}
    coerced = dict(args)
    for key, value in coerced.items():
        if not isinstance(value, str) or value.strip().casefold() not in _NULLISH_ARG_WORDS:
            continue
        field = fields.get(key)
        annotation = getattr(field, "annotation", None) if field is not None else None
        if type(None) in get_args(annotation):
            coerced[key] = None
    return coerced


async def _invoke_tool(tool_map: dict[str, Any], call: dict[str, Any]) -> str:
    """2026-08-07 用于按模型工具调用执行同步或异步 LangChain 工具

    2026-09-12 参数绑定发生在 langchain 工具 schema 层（先于函数体）；
    2026-09-13 实时写入后该层的 pydantic 失败统一翻成结构化拒绝回执
    （record/field/code/expected），只指向出错的那一条记录；
    2026-09-14 可空参数的 null 字面串在绑定前先按留空归一。
    """
    name = str(call.get("name"))
    candidate = tool_map.get(name)
    if candidate is None:
        raise ValueError(f"未知 annotation 工具: {name}")
    args = dict(call.get("args") or {})
    if name in _WRITE_TOOL_NAMES:
        args = _coerce_nullish_write_args(candidate, args)
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


def _tool_status_emitter(stream: AgentStream | None, observer: AgentTurnObserver | None) -> Any:
    """2026-09-15 用于构造工具状态事件出口；SSE 推送失败时先闭合回合审计计时再上抛"""

    async def emit(name: str, status: str, message: str) -> None:
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

    return emit


def _call_entry(
    call: dict[str, Any],
    *,
    index: int,
    content: str | None,
    status: str,
    error: str | None,
    receipt: dict[str, Any] | None,
    started_ns: int,
) -> dict[str, Any]:
    """2026-09-15 用于构造批次与程序面共用的调用结果条目"""
    return {
        "call": call,
        "index": index,
        "content": content,
        "status": status,
        "error": error,
        "receipt": receipt,
        "started_ns": started_ns,
    }


def _program_meta(meta: dict[str, Any], receipt: Any) -> dict[str, Any]:
    """2026-09-15 用于把程序面逐 op 定位字段并进审计行 request_args 的 _program"""
    body = dict(meta)
    if isinstance(receipt, dict):
        if receipt.get("record"):
            body["record"] = receipt["record"]
        if receipt.get("code"):
            body["error_code"] = receipt["code"]
    return body


async def _failed_entry(
    call: dict[str, Any],
    error_text: str,
    *,
    index: int,
    observer: AgentTurnObserver | None = None,
    stream: AgentStream | None = None,
) -> dict[str, Any]:
    """2026-09-15 用于把未执行调用（协议错误/流截断）渲染成独立失败回执与审计行"""
    name = str(call.get("name"))
    content = _failed_receipt(name, error_text)
    receipt = json.loads(content)
    started_ns = time.perf_counter_ns()
    if observer is not None:
        observer.record_tool_call(
            call_index=index,
            tool_name=name,
            request_args=dict(call.get("args") or {}),
            raw_args=(str(call.get("raw_args")) if call.get("raw_args") is not None else None),
            response=receipt,
            receipt=receipt,
            status="error",
            error=error_text,
            tool_duration_ms=0,
            started_ns=started_ns,
        )
    await _tool_status_emitter(stream, observer)(name, "error", error_text)
    return _call_entry(
        call,
        index=index,
        content=content,
        status="error",
        error=error_text,
        receipt=receipt,
        started_ns=started_ns,
    )


async def _execute_call(
    call: dict[str, Any],
    *,
    tool_map: dict[str, Any],
    ledger: AnnotationToolLedger,
    observer: AgentTurnObserver | None = None,
    stream: AgentStream | None = None,
    call_index: int,
    settle_finish: bool = False,
    program_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """2026-09-15 用于执行单条工具调用（原生 tool_batch 与程序面执行器共用同一实现）

    2026-09-13 实时写入语义原样保留：写入即生效；单条业务错误只回滚该条（账本与图
    各自快照恢复）、之前写入的记录保留；合同违反（AnnotationInvariantError）不可
    恢复，先闭合回合审计计时再上抛。finish_chapter 默认只登记（收尾判定由批次末尾
    统一结算），程序面在程序末尾调用时传 settle_finish=True 就地结算。
    """
    name = str(call.get("name"))
    started_ns = time.perf_counter_ns()
    if call.get("truncated"):
        return await _failed_entry(
            call,
            _truncated_error(name),
            index=call_index,
            observer=observer,
            stream=stream,
        )
    if name == "finish_chapter":
        # 收尾声明：校验与冻结推迟到本回合全部调用处理完之后
        # （逐条失败只回滚该调用、不阻塞收尾），因此"同轮多个小调用 + 收尾"仍计一个回合
        content = await _invoke_tool(tool_map, call)
        entry = _call_entry(
            call,
            index=call_index,
            content=content,
            status="pending",
            error=None,
            receipt=json.loads(content),
            started_ns=started_ns,
        )
        if settle_finish:
            await _settle_chapter_finish(
                ledger,
                [entry],
                observer=observer,
                emit_tool_status=_tool_status_emitter(stream, observer),
            )
        return entry
    ledger_snapshot = ledger.snapshot()
    graph_snapshot = ledger.graph.snapshot() if ledger.graph is not None else None
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
        result = _failed_receipt(name, exc)
        status = "error"
        error = str(exc)
        receipt = json.loads(result)
    if observer is not None:
        request_args = dict(call.get("args") or {})
        if program_meta is not None:
            request_args["_program"] = _program_meta(program_meta, receipt)
        observer.record_tool_call(
            call_index=call_index,
            tool_name=name,
            request_args=request_args,
            raw_args=(str(call.get("raw_args")) if call.get("raw_args") is not None else None),
            response=receipt,
            receipt=receipt,
            status=status,
            error=error,
            tool_duration_ms=max(0, round((time.perf_counter_ns() - started_ns) / 1_000_000)),
            started_ns=started_ns,
        )
    await _tool_status_emitter(stream, observer)(name, status, result if status == "success" else (error or ""))
    return _call_entry(
        call,
        index=call_index,
        content=result,
        status=status,
        error=error,
        receipt=receipt,
        started_ns=started_ns,
    )


def _build_tool_batch_node(
    tools: list[Any],
    *,
    ledger: AnnotationToolLedger,
    observer: AgentTurnObserver | None = None,
    stream: AgentStream | None = None,
    program_tool_name: str | None = None,
):
    """2026-08-10 用于构建逐调用独立提交且互不回滚的工具节点

    2026-09-13 实时写入：一个回合的多个调用串行处理、共享账本、写入即生效；
    finish_chapter 的收尾判定推迟到本回合全部调用处理完再执行，因此
    "同轮多个小调用 + 一个收尾声明"整体只计一个模型回合。失败只影响该调用自己，
    不影响同回合其他调用、也不阻塞收尾（收尾判定见 _settle_chapter_finish）。

    2026-09-15 program_tool_name：程序模式把绑定面收成唯一 execute_code，模型
    偶尔直发原生工具调用（实验 ch5 第一轮实测）——这类调用转入同一个内层
    dispatcher 并按同一套校验执行，审计记 direct_fallback；未知名逐条协议错误，
    同批其他调用照常执行、不执行任何写入。该容错层不依赖任何厂商 tool_choice 行为。
    """

    async def tool_batch(state: AnnotationGraphState) -> dict[str, Any]:
        """2026-09-13 用于独立串行执行本回合全部小调用并按单次调用边界回滚"""
        calls = _tool_calls(state)
        tool_map = {candidate.name: candidate for candidate in tools}
        allowed_tool_names = frozenset(tool_map)
        rendered: list[dict[str, Any]] = []
        if program_tool_name is None:
            protocol_error = _tool_batch_protocol_error(
                calls,
                allowed_tool_names=allowed_tool_names,
            )
            if protocol_error is not None:
                ledger.errors.append(protocol_error)
                for call_index, call in enumerate(calls):
                    rendered.append(
                        await _failed_entry(call, protocol_error, index=call_index, observer=observer, stream=stream)
                    )
                if observer is not None:
                    observer.close_turn()
                return {"messages": _tool_messages(rendered), "phase": ledger.phase}
        for call_index, call in enumerate(calls):
            name = str(call.get("name"))
            if program_tool_name is not None and name not in allowed_tool_names:
                error_text = f"本轮未开放工具: {[name]}"
                ledger.errors.append(error_text)
                rendered.append(
                    await _failed_entry(call, error_text, index=call_index, observer=observer, stream=stream)
                )
                continue
            direct_fallback = program_tool_name is not None and name != program_tool_name
            rendered.append(
                await _execute_call(
                    call,
                    tool_map=tool_map,
                    ledger=ledger,
                    observer=observer,
                    stream=stream,
                    call_index=call_index,
                    program_meta=(
                        {
                            "program_id": None,
                            "op_index": call_index,
                            "source_line": None,
                            "record": None,
                            "direct_fallback": True,
                        }
                        if direct_fallback
                        else None
                    ),
                )
            )
        await _settle_chapter_finish(
            ledger,
            rendered,
            observer=observer,
            emit_tool_status=_tool_status_emitter(stream, observer),
        )
        if observer is not None:
            observer.close_turn()
        return {"messages": _tool_messages(rendered), "phase": ledger.phase}

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
        # 2026-09-15 回填条目状态与结构化回执：程序面按 entry 统计 op 成败并渲染失败清单
        entry["status"] = status
        entry["error"] = error
        entry["receipt"] = json.loads(content)
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
    bind_tools: list[Any] | None = None,
    program_tool_name: str | None = None,
) -> Any:
    """2026-08-10 用于构建逐 chunk 领域写入和章节自动完成状态机（消息链累积）

    2026-09-14 写者面每回合注入【进度账本】（inject_progress）；读者图不开。
    2026-09-15 程序面（CodeAct）：bind_tools 把绑定面收成唯一 execute_code，
    tools 仍是完整分发字典；program_tool_name 非空时批次按程序模式处理协议错误
    与直发原生调用（见 _build_tool_batch_node）。
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
            inject_progress=True,
            bind_tools=bind_tools,
            program_mode=program_tool_name is not None,
        ),
    )
    graph.add_node(
        "tool_batch",
        _build_tool_batch_node(
            tools,
            ledger=ledger,
            observer=observer,
            stream=stream,
            program_tool_name=program_tool_name,
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
    """2026-09-11 用于读者循环路由：错误收口、工具批次、无工具回复即上报完毕（§8.5）

    2026-09-16 块代理面复用本路由：撞轮次上限时 halted 置位，同样按会话收束结束。
    """
    if state.get("error") or state.get("halted"):
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


def build_block_graph(
    llm: Any,
    program_tool: Any,
    *,
    ledger: AnnotationToolLedger,
    max_iterations: int,
    stream: AgentStream | None = None,
    observer: AgentTurnObserver | None = None,
    retries: int | None = None,
) -> Any:
    """2026-09-16 块代理程序面用于构建块会话状态机（对外唯一绑定面 execute_code）

    与读者面同构：没有写入工具、没有领域冻结、没有缺域提醒，无工具回复即"本块
    标注完毕"；两处差别是撞轮次上限按会话自然收束（stop_at_iteration_limit）与
    绑定面收成唯一 execute_code（模型直发原生工具名一律协议错误，不落到任何写入）。
    """
    bind_tools = [program_tool]
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
            completion_hint=None,
            require_tool_call=False,
            bind_tools=bind_tools,
            program_mode=True,
            stop_at_iteration_limit=True,
        ),
    )
    graph.add_node(
        "tool_batch",
        _build_tool_batch_node(
            bind_tools,
            ledger=ledger,
            observer=observer,
            stream=stream,
            program_tool_name=program_tool_name,
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


__all__ = ["AnnotationGraphState", "build_annotation_graph", "build_block_graph", "build_reader_graph"]
