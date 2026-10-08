"""当前 work 会话共用的模型节点和工具调用解析

消息链采用 messages + add_messages 累积，每次请求携带完整历史。
角色独立调用 finish 校验并关闭写入；实际持久化和保存确认由队列执行。
会话自然结束或达到轮次上限不代表 work 已完成。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated, Any, Literal, NotRequired, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph.message import add_messages

from src.agents.annotation.ledger import AnnotationToolLedger

from .errors import AnnotationStageRejection
from .graph_texts import _turn_budget_reminder

if TYPE_CHECKING:
    from src.agents.stream import AgentStream
    from src.agents.turn_observer import AgentTurnObserver

# 2026-08-14 D1：无 continuity_open 阶段，chapter_open -> completed 两态
AnnotationPhase = Literal["chapter_open", "completed"]

# 2026-09-05 剩余轮次（含本轮）进入该窗口即向本次请求追加收尾提醒
TURN_BUDGET_REMINDER_WINDOW = 3


class AnnotationGraphState(TypedDict):
    """2026-08-10 用于保存逐章 工具循环的累积消息链"""

    messages: Annotated[list[BaseMessage], add_messages]
    phase: AnnotationPhase
    iterations: int
    error: str | None
    # 达到轮次上限只停止模型循环，未成功 finish 的 work 由队列判败并安排重试
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
):
    """执行当前 work 会话；达到轮次上限只结束模型循环，保存仍要求成功 finish"""
    advertised = list(tools)

    async def agent_node(state: AnnotationGraphState) -> dict[str, Any]:
        """2026-08-10 用于执行一次绑定语义工具合同的模型调用"""
        iterations = int(state.get("iterations") or 0)
        if iterations >= max_iterations:
            return {"halted": True}
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
                    )
                )
            )

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
                require_tool_call=False,
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


__all__ = ["AnnotationGraphState"]
