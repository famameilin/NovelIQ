"""当前 work 会话共用的模型节点和工具调用解析

消息链采用 messages + add_messages 累积，每次请求携带完整历史。
finish 和无工具响应都请求程序检查；通过后由队列执行持久化和保存确认。
缺项继续同一会话；达到轮次上限交回模型池重选。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Annotated, Any, Literal, NotRequired, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph.message import add_messages
from loguru import logger

from src.agents.annotation.ledger import AnnotationToolLedger
from src.agents.context_compaction import (
    build_fallback_note,
    build_summary_messages,
    build_visible_messages,
    context_limits,
    frame_summary,
    measure_context_tokens,
    response_text,
    select_compaction,
    split_prefix,
    tool_schema_tokens,
)

from .errors import AnnotationStageRejection
from .graph_texts import _turn_budget_reminder

if TYPE_CHECKING:
    from src.agents.stream import AgentStream
    from src.agents.turn_observer import AgentTurnObserver

# 阶段取值：chapter_open -> completed
AnnotationPhase = Literal["chapter_open", "completed"]

# 剩余轮次（含本轮）进入该窗口即向本次请求追加收尾提醒
TURN_BUDGET_REMINDER_WINDOW = 3


class AnnotationGraphState(TypedDict):
    """用于保存逐章 工具循环的累积消息链"""

    messages: Annotated[list[BaseMessage], add_messages]
    phase: AnnotationPhase
    iterations: int
    error: str | None
    # 回合耗尽交回模型池；结束请求的完整性由 check 节点判定
    halted: NotRequired[bool]
    completion_ok: NotRequired[bool]
    missing: NotRequired[list[str]]
    end_signal: NotRequired[str]
    # 上下文压缩：模型可见摘要与已遮蔽的消息条数（从首个 AI 消息起计数）
    compaction_summary: NotRequired[str | None]
    shadowed_message_count: NotRequired[int]


def _build_agent_node(
    llm: Any,
    tools: list[Any],
    *,
    ledger: AnnotationToolLedger,
    max_iterations: int,
    context_window_tokens: int | None = None,
    stream: AgentStream | None = None,
    observer: AgentTurnObserver | None = None,
    retries: int | None = None,
    thinking_message: Callable[[int], str] | None = None,
):
    """执行当前 work 会话；达到轮次上限返回，只有程序检查通过才能保存

    thinking_message：轮推理提示文案可由调用侧定制（诊断等非章节面复用同一节点），
    缺省保持章节标注文案不改。
    context_window_tokens：上下文容量；请求达到其 90% 时把早期工具轮压成摘要。
    """
    advertised = list(tools)
    schema_tokens = tool_schema_tokens(advertised)

    def _thinking_text(rounds: int) -> str:
        if thinking_message is not None:
            return thinking_message(rounds)
        return f"章节标注推理中（第 {rounds} 轮）..."

    def _callbacks(context_summary: dict[str, Any], request_messages: list[Any]):
        """用于为一次物理 Provider 请求绑定审计上下文与请求消息"""

        def on_turn_started(provider_request: dict[str, Any], started_ns: int) -> None:
            """用于在物理 Provider 请求发送前写入独立审计行"""
            if observer is None:
                return
            observer.begin_provider_turn(
                context_summary=context_summary,
                request_messages=request_messages,
                provider_request=provider_request,
                started_ns=started_ns,
            )

        def on_turn_complete(message: AIMessage, timing: Any) -> None:
            """用于收口成功的物理 Provider 请求审计"""
            if observer is None:
                return
            observer.complete_provider_turn(response_message=message, timing=timing)

        def on_turn_failed(error: str, timing: Any, message: AIMessage | None) -> None:
            """用于收口断流超时和无工具回复的物理 Provider 请求审计"""
            if observer is None:
                return
            observer.fail_provider_turn(error=error, timing=timing, response_message=message)

        return on_turn_started, on_turn_complete, on_turn_failed

    async def agent_node(state: AnnotationGraphState) -> dict[str, Any]:
        """用于执行一次绑定语义工具合同的模型调用"""
        iterations = int(state.get("iterations") or 0)
        if iterations >= max_iterations:
            return {"halted": True}
        ledger.set_phase(state["phase"])
        from src.agents.stream import ModelRequestError, run_model_call

        summary = state.get("compaction_summary")
        shadowed_count = int(state.get("shadowed_message_count") or 0)
        visible = build_visible_messages(state["messages"], summary=summary, shadowed_count=shadowed_count)
        request_messages = list(visible)
        compaction_state: dict[str, Any] = {}
        compaction_info: dict[str, Any] | None = None

        if context_window_tokens:
            trigger_tokens, retain_tokens = context_limits(context_window_tokens)
            usage_tokens = measure_context_tokens(visible, tool_schema_tokens=schema_tokens)
            if usage_tokens >= trigger_tokens:
                prefix, _ = split_prefix(state["messages"])
                unshadowed = list(state["messages"][len(prefix) + shadowed_count :])
                selection = select_compaction(unshadowed, retain_tokens=retain_tokens)
                if selection is not None:
                    shadowed, kept = selection
                    if stream is not None:
                        await stream.thinking("上下文接近容量上限，正在生成压缩摘要...")
                    summary_messages = build_summary_messages(
                        prefix, previous_summary=summary, shadowed=shadowed
                    )
                    summary_context = {
                        **ledger.context_summary(),
                        "allowed_tool_names": [],
                        "purpose": "context_compaction",
                        "shadowed_messages": len(shadowed),
                        "retained_messages": len(kept),
                    }
                    started, complete, failed = _callbacks(summary_context, summary_messages)
                    fallback = False
                    try:
                        summary_response = await run_model_call(
                            llm,
                            summary_messages,
                            None,
                            on_turn_complete=complete,
                            on_turn_started=started,
                            on_turn_failed=failed,
                            total_attempts=retries,
                            require_tool_call=False,
                        )
                        text = response_text(summary_response)
                        if not text:
                            raise ValueError("摘要回复为空")
                    except (ModelRequestError, ValueError) as exc:
                        logger.warning("上下文压缩摘要失败，改用确定性裁剪: {}", exc)
                        framed = build_fallback_note(shadowed)
                        fallback = True
                    else:
                        framed = frame_summary(text)
                    compaction_state = {
                        "compaction_summary": framed,
                        "shadowed_message_count": shadowed_count + len(shadowed),
                    }
                    request_messages = [*prefix, HumanMessage(content=framed), *kept]
                    compaction_info = {
                        "shadowed_messages": len(shadowed),
                        "retained_messages": len(kept),
                        "usage_tokens": usage_tokens,
                        "trigger_tokens": trigger_tokens,
                        "context_window_tokens": context_window_tokens,
                        "fallback": fallback,
                    }
                    logger.info(
                        "context_compaction shadowed_messages={} retained_messages={} usage_tokens={} "
                        "trigger_tokens={} context_window_tokens={} fallback={}",
                        len(shadowed),
                        len(kept),
                        usage_tokens,
                        trigger_tokens,
                        context_window_tokens,
                        fallback,
                    )

        if stream is not None:
            await stream.thinking(_thinking_text(iterations + 1))

        remaining_turns = max_iterations - iterations
        # 注入顺序：先追加【轮次预算】提醒；进度账本只进审计的 context_summary，
        # 不写进请求消息链，本请求对模型可见的末条仍是状态消息链自身。
        if remaining_turns <= TURN_BUDGET_REMINDER_WINDOW:
            request_messages.append(
                HumanMessage(
                    content=_turn_budget_reminder(
                        remaining_turns,
                        total=max_iterations,
                    )
                )
            )

        context_summary = {
            **ledger.context_summary(),
            "allowed_tool_names": [candidate.name for candidate in advertised],
        }
        if compaction_info is not None:
            context_summary["context_compaction"] = compaction_info

        on_turn_started, on_turn_complete, on_turn_failed = _callbacks(context_summary, request_messages)
        try:
            response = await run_model_call(
                llm.bind_tools(advertised),
                request_messages,
                stream,
                on_turn_complete=on_turn_complete,
                on_turn_started=on_turn_started,
                on_turn_failed=on_turn_failed,
                total_attempts=retries,
                require_tool_call=False,
            )
        except Exception:
            raise
        return {"messages": [response], "iterations": iterations + 1, **compaction_state}

    return agent_node


def _tool_calls(state: AnnotationGraphState) -> list[dict[str, Any]]:
    """用于读取最后一条模型消息的工具调用列表"""
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        return []
    return [dict(call) for call in last_message.tool_calls]


def _failed_receipt(name: str, error: str | BaseException) -> str:
    """用于构造单个调用失败时模型可见的独立回执

    结构化拒绝（AnnotationStageRejection）只回 record/field/code/
    expected 与可自纠说明，不重复整份合同。
    """
    if isinstance(error, AnnotationStageRejection):
        return json.dumps(error.receipt(), ensure_ascii=False)
    return json.dumps(
        {"accepted": False, "tool": name, "error": str(error)},
        ensure_ascii=False,
    )


__all__ = ["AnnotationGraphState"]
