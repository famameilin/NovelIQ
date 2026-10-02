"""
章节标注逐章 语义写入 LangGraph

消息链采用 messages + add_messages 累积；每次模型请求携带完整历史消息。
冻结与章节组装由程序自动执行：模型用唯一 finish 收尾后
图节点自动冻结章 并完成章节，模型不需要调用完成工具。

2026-09-13 实时写入：一个模型回合可以包含多个有类型的小调用（每条只写一个完整
语义单元、写入即生效），写完全部内容后用 finish 收尾；收尾判定推迟到本回合
全部调用处理完毕之后（逐条失败只回滚该调用、不阻塞收尾），因此一次回复整体仍计
一个回合。

2026-09-18 模型可见面收敛：正式与连续性信封都只绑定 [execute_code, finish]，
其余工具（检索、案例、写入、构造器）一律进 execute_code 的程序面。
"""

# ruff: noqa: E402 —— 文件末尾的 re-export 导入为有意的延迟导入（大文件拆分聚合面）。

# 创建时间：2026-10-02　创建者：Trae
# 任务：graph.py 大文件拆分——批执行核心迁出至 tool_batch.py，subagent 图迁出至
# subagent_graph.py，预算/缺域提醒文案 helpers 迁出至 graph_texts.py；本模块保留
# AnnotationGraphState/agent 节点/路由/章结算/auto_finalize/build_annotation_graph
# 并对迁出符号 re-export（既有导入方零改动）。
# 说明：纯结构搬移，不改任何运行逻辑与签名。

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Annotated, Any, Literal, NotRequired, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from .errors import AnnotationInvariantError, AnnotationStageRejection
from .graph_texts import _missing_domains_reminder, _progress_block, _turn_budget_reminder
from .tools import FINISH_TOOL_NAME, AnnotationToolLedger

if TYPE_CHECKING:
    from src.agents.audit.observer import AgentTurnObserver
    from src.agents.stream import AgentStream

# 2026-08-14 D1：无 continuity_open 阶段，chapter_open -> completed 两态
AnnotationPhase = Literal["chapter_open", "completed"]

# 2026-09-05 剩余轮次（含本轮）进入该窗口即向本次请求追加收尾提醒
TURN_BUDGET_REMINDER_WINDOW = 3

# 2026-09-11 章内并行：区分"未传 completion_hint"（用缺内容提醒）与显式传 None（无提醒）
_HINT_SENTINEL = object()


class AnnotationGraphState(TypedDict):
    """2026-08-10 用于保存逐章 工具循环的累积消息链"""

    messages: Annotated[list[BaseMessage], add_messages]
    phase: AnnotationPhase
    iterations: int
    error: str | None
    # 2026-09-16 块代理面：轮次上限按"会话自然收束"处理（局部标注是内存对象、
    # 构造即校验，撞上限只是停止会话，不是失败）；写者/读者面不置位、行为不变
    halted: NotRequired[bool]


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
    subagent_face: bool = False,
    stop_at_iteration_limit: bool = False,
):
    """同步账本阶段、限制模型轮次并注入一次性进度提醒

    绑定面只含 execute_code 与 finish，执行面保留本信封的完整工具表。
    2026-10-02 恢复 subagent 面参数：subagent_face=True 时撞顶文案按会话收束措辞，
    stop_at_iteration_limit=True 时撞顶返回 halted（会话自然收束，不按失败上报）。
    """

    advertised = list(bind_tools) if bind_tools is not None else list(tools)

    if completion_hint is _HINT_SENTINEL:

        def completion_hint() -> str | None:
            """2026-09-13 无工具回复重发前按账本当前尚无内容的领域生成一次性提醒"""
            return _missing_domains_reminder(ledger.missing_content_domains())

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
        # 2026-09-20 注入顺序：先【轮次预算】提醒、【进度账本】恒为本请求的最后一条。
        # 账本每轮现算现挂、从不写进状态消息链，所以"每轮开始前移除上一轮"是构造性的：
        # 上一轮那份随请求结束消失，本轮请求里只有本轮的新块（run 54a72932 实测 523 个
        # 请求零重复）。放末位是因为模型生成前最后读到的必须先是本章当前状态。
        if remaining_turns <= TURN_BUDGET_REMINDER_WINDOW:
            request_messages.append(
                HumanMessage(
                    content=_turn_budget_reminder(
                        remaining_turns,
                        total=max_iterations,
                        subagent_face=subagent_face,
                    )
                )
            )
        if inject_progress:
            request_messages.append(HumanMessage(content=_progress_block(ledger, remaining_turns, max_iterations)))

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


async def _settle_chapter_finish(
    ledger: AnnotationToolLedger,
    rendered: list[dict[str, Any]],
    *,
    observer: AgentTurnObserver | None,
    emit_tool_status: Any,
    chapter_finish_name: str | None = FINISH_TOOL_NAME,
) -> None:
    """2026-09-13 用于在本回合全部调用处理完后执行 finish 收尾判定

    写入是实时的、不需要结算：本回合的逐条失败各自在调用点已回执，收尾只管
    按已写入内容补默认判定、校验并构造 ready_chapter（构造失败整体回滚，已写入记录保留）。
    2026-09-18 chapter_finish_name 为 None 的面（subagent 面）直接跳过：它的同名 finish
    只是本 subagent 的收尾声明，不冻结整章、也不在批次末尾结算。
    """
    if chapter_finish_name is None:
        return
    for entry in rendered:
        call = entry["call"]
        if str(call.get("name")) != chapter_finish_name or entry.get("content") is None:
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
            content = _failed_receipt(chapter_finish_name, exc)
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
                tool_name=chapter_finish_name,
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
            await emit_tool_status(chapter_finish_name, "success", content)
        else:
            await emit_tool_status(chapter_finish_name, "error", error or "")


def _build_auto_finalize_node(
    ledger: AnnotationToolLedger,
    *,
    stream: AgentStream | None = None,
    observer: AgentTurnObserver | None = None,
):
    """2026-09-13 用于在收尾声明后自动冻结章 并完成章节"""

    async def auto_finalize(state: AnnotationGraphState) -> dict[str, Any]:
        """2026-09-13 用于在 finish 收尾后冻结章 并完成章节"""
        if ledger.phase != "chapter_open":
            return {"phase": ledger.phase}
        if not ledger.chapter_finished:
            return {"phase": ledger.phase}
        try:
            if stream is not None:
                await stream.tool_call_started("auto_freeze_chapter")
            ledger.complete_active_chapter()
            if stream is not None:
                await stream.tool_call_succeeded("auto_freeze_chapter", "chapter frozen")
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
    """2026-08-10 用于构建逐章 领域写入和章节自动完成状态机（消息链累积）

    2026-09-14 写者面每回合注入【进度账本】（inject_progress）；读者图不开。
    2026-09-15 程序面（CodeAct）：bind_tools 决定绑定面（写者面 [execute_code, finish]），
    tools 仍是完整分发字典；program_tool_name 非空时批次按程序模式处理协议错误
    与直发原生调用（见 _build_tool_batch_node）。
    2026-09-18 模型可见面 = bind_tools（写者面即 [execute_code, finish]）；本章级
    收尾工具名取默认 FINISH_TOOL_NAME，收尾判定与批次末尾结算照旧。
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


from .subagent_graph import build_subagent_graph as build_subagent_graph  # noqa: E402
from .tool_batch import (  # noqa: E402
    _build_tool_batch_node as _build_tool_batch_node,
)
from .tool_batch import (
    _execute_call as _execute_call,
)
from .tool_batch import (
    _invoke_tool as _invoke_tool,
)

__all__ = ["AnnotationGraphState", "build_annotation_graph", "build_subagent_graph"]
