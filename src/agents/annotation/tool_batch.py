"""
章节标注批执行核心：工具调用执行、批次节点与回执消息渲染（原生批次与程序面共用）
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any, get_args

from langchain_core.messages import ToolMessage
from pydantic import ValidationError

from src.agents.annotation.ledger import AnnotationToolLedger
from src.agents.annotation.tools import _WRITE_TOOL_NAMES
from src.agents.annotation.validation_errors import translate_write_validation_error

from .errors import AnnotationDependencyError, AnnotationInvariantError
from .graph import (
    AnnotationGraphState,
    _failed_receipt,
    _tool_calls,
)

if TYPE_CHECKING:
    from src.agents.stream import AgentStream
    from src.agents.turn_observer import AgentTurnObserver


def _tool_batch_protocol_error(
    calls: list[dict[str, Any]],
    *,
    allowed_tool_names: frozenset[str],
) -> str | None:
    """用于校验模型回合只调用本轮开放的工具"""
    if not calls:
        return "每个模型回合必须调用工具"
    unavailable = [str(call.get("name")) for call in calls if str(call.get("name")) not in allowed_tool_names]
    if unavailable:
        return f"本轮未开放工具: {unavailable}"
    return None


_NULLISH_ARG_WORDS = frozenset({"null", "none", "nil", ""})


def _coerce_nullish_write_args(tool: Any, args: dict[str, Any]) -> dict[str, Any]:
    """null 字面串统一容错：可空参数按留空读取

    写入类工具的参数里，凡 schema 声明可空（Optional）的参数，null 类字面串一律按留空
    读取；必填参数不改，交给账本校验/类型报错。转换放在生产调用入口而不是工具签名：
    @tool 保留真实类型（enum/union）但剥掉 Annotated 的 BeforeValidator。
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
    """用于按模型工具调用执行同步或异步 LangChain 工具

    参数绑定发生在 langchain 工具 schema 层（先于函数体），该层的 pydantic 失败统一翻成
    结构化拒绝回执（record/field/code/expected），只指向出错的那一条记录；
    可空参数的 null 字面串在绑定前先按留空归一。
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
        # 关联工具也报告记录键与失败值，沿用原有参数校验与取值规则
        if name in _WRITE_TOOL_NAMES | {"anchor_record", "write_link"}:
            raise translate_write_validation_error(name, args, exc) from None
        raise
    return str(result)


def _truncated_error(name: str) -> str:
    """用于构造流截断调用不执行写入时模型可见的独立回执"""
    return (
        f"模型工具 {name} 的参数不完整（流传输截断，参数 JSON 在对象中间被切断），"
        "本次未执行任何写入，请重新提交完整参数。"
    )


def _tool_status_emitter(stream: AgentStream | None, observer: AgentTurnObserver | None) -> Any:
    """用于构造工具状态事件出口；SSE 推送失败时先闭合回合审计计时再上抛"""

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
    """用于构造批次与程序面共用的调用结果条目"""
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
    """用于把程序面逐 op 定位字段并进审计行 request_args 的 _program"""
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
    """用于把未执行调用（协议错误/流截断）渲染成独立失败回执与审计行"""
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
    program_meta: dict[str, Any] | None = None,
    record_keys: set[str] | None = None,
) -> dict[str, Any]:
    """原生调用和程序内部调用共用单条事务及审计边界

    单条业务错误只撤销该调用，已成功产出保留；共享状态由 Agent 自己按贡献回滚。
    finish 仅请求结束，同批工具全部执行。合同违反不可恢复，闭合审计后上抛。
    成功记录键即时登记，供后续原文锚点校验。
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
    ledger_snapshot = ledger.snapshot()
    graph_snapshot = ledger.graph.snapshot() if ledger.graph is not None and ledger.invoke_tool is None else None
    dependency_error: AnnotationDependencyError | None = None
    try:
        if stream is not None:
            await stream.tool_call_started(name)
        result = (
            await ledger.invoke_tool(tool_map, call)
            if ledger.invoke_tool is not None
            else await _invoke_tool(tool_map, call)
        )
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
        if isinstance(exc, AnnotationDependencyError):
            dependency_error = exc
    if record_keys is not None and status == "success" and isinstance(receipt, dict):
        written_record = receipt.get("record")
        if isinstance(written_record, str) and written_record:
            record_keys.add(written_record)
    audit_status, audit_error = status, error
    audit_receipt = receipt
    if name == "execute_code" and isinstance(receipt, dict):
        # 返回 JSON 成功不代表业务全部成功；只改变监控口径，保留已生效写入与逐条事务语义
        business_status = str(receipt.get("status") or "unknown")
        audit_receipt = {**receipt, "execution_status": status, "business_status": business_status}
        if status == "success" and business_status in {"partial", "runtime_error", "rejected"}:
            audit_status = "error"
            detail = receipt.get("error") or receipt.get("failed") or ""
            audit_error = f"业务回执 status={business_status}，已生效调用={receipt.get('applied', 0)}；{detail}"
    if observer is not None:
        request_args = dict(call.get("args") or {})
        if program_meta is not None:
            request_args["_program"] = _program_meta(program_meta, receipt)
        observer.record_tool_call(
            call_index=call_index,
            tool_name=name,
            request_args=request_args,
            raw_args=(str(call.get("raw_args")) if call.get("raw_args") is not None else None),
            response=audit_receipt,
            receipt=audit_receipt,
            error=audit_error,
            tool_duration_ms=max(0, round((time.perf_counter_ns() - started_ns) / 1_000_000)),
            started_ns=started_ns,
        )
    await _tool_status_emitter(stream, observer)(
        name,
        audit_status,
        result if audit_status == "success" else (audit_error or ""),
    )
    if dependency_error is not None:
        # 先记录失败调用，再中止本批和模型会话，不返回可修正回执
        if observer is not None:
            observer.close_turn()
        raise dependency_error
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
    """串行执行本回合调用，各调用独立校验、回滚和审计

    只允许实际绑定的工具名；程序模式下未知调用逐条拒绝，不影响同批其他调用。
    同批 finish 后仍执行剩余调用，再由程序检查完整性。
    """

    async def tool_batch(state: AnnotationGraphState) -> dict[str, Any]:
        """用于独立串行执行本回合全部小调用并按单次调用边界回滚"""
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
                # 程序面绑定的只有程序工具与收尾工具，模型偶尔直发原生工具名。原生名一律
                # 不进写入面，回执只报事实：调用方式属提示词面（execute_code 的说明 +
                # 系统提示词），不在回执里复述模型自己看得到的工具面。
                error_text = f"本轮未开放工具: {[name]}"
                ledger.errors.append(error_text)
                rendered.append(
                    await _failed_entry(call, error_text, index=call_index, observer=observer, stream=stream)
                )
                continue
            direct_fallback = program_tool_name is not None and name not in {
                program_tool_name,
                program_tool_name,
            }
            rendered.append(
                await _execute_call(
                    call,
                    tool_map=tool_map,
                    ledger=ledger,
                    observer=observer,
                    stream=stream,
                    call_index=call_index,
                    # 写入成功即登记当前 work 的记录键，供原文锚点使用
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
        if observer is not None:
            observer.close_turn()
        return {"messages": _tool_messages(rendered), "phase": ledger.phase}

    return tool_batch


def _tool_messages(rendered: list[dict[str, Any]]) -> list[ToolMessage]:
    """按调用顺序渲染模型可见回执，包括失败和即时收尾结果"""
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
