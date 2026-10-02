"""
章节标注批执行核心：工具调用执行、批次节点与回执消息渲染（原生批次与程序面共用）
"""

# 创建时间：2026-10-02　创建者：Trae
# 任务：graph.py 大文件拆分——批执行核心（_tool_status_emitter/_call_entry/_program_meta/
# _failed_entry/_execute_call/_build_tool_batch_node/_tool_messages 及其专属 helper）迁入本模块
# 说明：纯结构搬移，不改任何运行逻辑与签名；_failed_receipt/_tool_calls/_settle_chapter_finish
# 等 graph.py 保留件由本模块反向引用（graph.py 末尾 re-export 本模块符号，导入方零改动）。

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any, get_args

from langchain_core.messages import ToolMessage
from pydantic import ValidationError

from .errors import AnnotationInvariantError
from .graph import (
    AnnotationGraphState,
    _failed_receipt,
    _settle_chapter_finish,
    _tool_calls,
)
from .tools import (
    _WRITE_TOOL_NAMES,
    FINISH_TOOL_NAME,
    AnnotationToolLedger,
    translate_write_validation_error,
)

if TYPE_CHECKING:
    from src.agents.audit.observer import AgentTurnObserver
    from src.agents.stream import AgentStream


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
    receipt: Any,
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
    chapter_finish_name: str | None = FINISH_TOOL_NAME,
    record_keys: set[str] | None = None,
) -> dict[str, Any]:
    """2026-09-15 用于执行单条工具调用（原生 tool_batch 与程序面执行器共用同一实现）

    2026-09-13 实时写入语义原样保留：写入即生效；单条业务错误只回滚该条（账本与图
    各自快照恢复）、之前写入的记录保留；合同违反（AnnotationInvariantError）不可
    恢复，先闭合回合审计计时再上抛。finish 默认只登记（收尾判定由批次末尾统一结算），
    程序面在程序末尾调用时传 settle_finish=True 就地结算。
    2026-09-18 收尾工具名的两个面同名（都叫 finish）：只有写者面的 finish 是章级收尾，
    传 None 的面（subagent 面）按普通工具执行——subagent 的 finish 只声明本 subagent 完毕。
    2026-10-02 恢复 chapter_finish_name：随章内三子代理路径一并加回。
    成功回执的记录键即时登记，push_case 只能绑定本章实际产出
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
    if chapter_finish_name is not None and name == chapter_finish_name:
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
    if record_keys is not None and status == "success" and isinstance(receipt, dict):
        written_record = receipt.get("record")
        if isinstance(written_record, str) and written_record:
            record_keys.add(written_record)
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
    chapter_finish_name: str | None = FINISH_TOOL_NAME,
):
    """2026-08-10 用于构建逐调用独立提交且互不回滚的工具节点

    2026-09-13 实时写入：一个回合的多个调用串行处理、共享账本、写入即生效；
    finish 的收尾判定推迟到本回合全部调用处理完再执行，因此
    "同轮多个小调用 + 一个收尾声明"整体只计一个模型回合。失败只影响该调用自己，
    不影响同回合其他调用、也不阻塞收尾（收尾判定见 _settle_chapter_finish）。

    2026-09-15 program_tool_name：程序模式绑定面收成程序面工具（写者面
    [execute_code, finish]），模型偶尔直发原生工具调用（实验 ch5 第一轮实测）——这类调用转入同一个内层
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
                # 程序面绑定的只有程序工具与收尾工具，模型偶尔直发原生工具名（run 54a72932
                # 实测 25 次）。原生名一律不进写入面，回执只报事实：调用方式属提示词面
                # （execute_code 的说明 + 系统提示词），不在回执里复述模型自己看得到的工具面。
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
                    chapter_finish_name=chapter_finish_name,
                    # 原生面的回执就是模型读到的回执：写入成功即把 record 登记进章级账本，
                    # push_case.record_id / promise_case.result_id 按它校验
                    record_keys=ledger.written_record_keys,
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
            chapter_finish_name=chapter_finish_name,
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
