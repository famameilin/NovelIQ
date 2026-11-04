"""会话模型调用、上下文压缩与物理请求审计"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from loguru import logger

from src.agents.annotation.graph_texts import _turn_budget_reminder
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
from src.agents.loop import AgentState
from src.agents.messages import AssistantMessage, UserMessage

if TYPE_CHECKING:
    from src.agents.stream import AgentStream
    from src.agents.turn_observer import AgentTurnObserver

TURN_BUDGET_REMINDER_WINDOW = 3


def build_model_step(
    llm: Any,
    tools: list[Any],
    *,
    context_summary: Callable[[], dict[str, Any]],
    before_round: Callable[[AgentState], None] | None = None,
    max_iterations: int,
    context_window_tokens: int | None = None,
    stream: AgentStream | None = None,
    observer: AgentTurnObserver | None = None,
    retries: int | None = None,
    thinking_message: Callable[[int], str] | None = None,
):
    """执行一轮模型调用，保留预算、上下文压缩与独立请求审计

    上下文达到容量的 90% 时压缩早期工具轮，推理提示由调用侧定制
    """
    advertised = list(tools)
    schema_tokens = tool_schema_tokens(advertised)

    def _thinking_text(rounds: int) -> str:
        if thinking_message is not None:
            return thinking_message(rounds)
        return f"章节标注推理中（第 {rounds} 轮）..."

    def _callbacks(summary_context: dict[str, Any], request_messages: list[Any]):
        """用于为一次物理 Provider 请求绑定审计上下文与请求消息"""

        def on_turn_started(provider_request: dict[str, Any], started_ns: int) -> None:
            """用于在物理 Provider 请求发送前写入独立审计行"""
            if observer is None:
                return
            observer.begin_provider_turn(
                context_summary=summary_context,
                request_messages=request_messages,
                provider_request=provider_request,
                started_ns=started_ns,
            )

        def on_turn_complete(message: AssistantMessage, timing: Any) -> None:
            """用于收口成功的物理 Provider 请求审计"""
            if observer is None:
                return
            observer.complete_provider_turn(response_message=message, timing=timing)

        def on_turn_failed(error: str, timing: Any, message: AssistantMessage | None) -> None:
            """用于收口断流超时和无工具回复的物理 Provider 请求审计"""
            if observer is None:
                return
            observer.fail_provider_turn(error=error, timing=timing, response_message=message)

        return on_turn_started, on_turn_complete, on_turn_failed

    async def agent_node(state: AgentState) -> dict[str, Any]:
        """用于执行一次绑定语义工具合同的模型调用"""
        iterations = int(state.get("iterations") or 0)
        if iterations >= max_iterations:
            return {"halted": True}
        if before_round is not None:
            before_round(state)
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
                    summary_messages = build_summary_messages(prefix, previous_summary=summary, shadowed=shadowed)
                    summary_context = {
                        **context_summary(),
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
                    request_messages = [*prefix, UserMessage(content=framed), *kept]
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
                UserMessage(
                    content=_turn_budget_reminder(
                        remaining_turns,
                        total=max_iterations,
                    )
                )
            )

        turn_context = {
            **context_summary(),
            "allowed_tool_names": [candidate.name for candidate in advertised],
        }
        if compaction_info is not None:
            turn_context["context_compaction"] = compaction_info

        on_turn_started, on_turn_complete, on_turn_failed = _callbacks(turn_context, request_messages)
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
        return {"messages": [response], "iterations": iterations + 1, **compaction_state}

    return agent_node
