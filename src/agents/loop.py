"""模型、串行工具批次和领域完成检查的异步会话循环"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NotRequired, Protocol, TypedDict, cast

from src.agents.messages import AssistantMessage, Message, UserMessage, merge_messages

if TYPE_CHECKING:
    from src.agents.turn_observer import AgentTurnObserver


class AgentState(TypedDict):
    """当前 invocation 的消息、预算和完成状态"""

    messages: list[Message]
    iterations: int
    error: str | None
    phase: NotRequired[str]
    halted: NotRequired[bool]
    completion_ok: NotRequired[bool]
    missing: NotRequired[list[str]]
    end_signal: NotRequired[str]
    compaction_summary: NotRequired[str | None]
    shadowed_message_count: NotRequired[int]


class EndRequest(Protocol):
    """当前批次的结束意图"""

    end_requested: bool


@dataclass
class SessionControl:
    """不依赖领域账本的会话控制状态"""

    end_requested: bool = False


def tool_calls(state: AgentState) -> list[dict[str, Any]]:
    """读取完整模型回复中的工具调用"""
    last = state["messages"][-1]
    return [dict(call) for call in last.tool_calls] if isinstance(last, AssistantMessage) else []


class AgentLoop:
    """串行驱动一个 invocation，完成检查通过后才返回成功"""

    def __init__(
        self,
        model_step: Callable[[AgentState], Awaitable[dict[str, Any]]],
        execute_batch: Callable[[AgentState], Awaitable[dict[str, Any]]],
        *,
        end_state: EndRequest,
        completion_check: Callable[[], list[str]] | None,
        observer: AgentTurnObserver | None = None,
    ) -> None:
        self.model_step = model_step
        self.execute_batch = execute_batch
        self.end_state = end_state
        self.completion_check = completion_check
        self.observer = observer

    @staticmethod
    def _update(state: AgentState, update: dict[str, Any]) -> None:
        if "messages" in update:
            update = {**update, "messages": merge_messages(state["messages"], update["messages"])}
        state.update(cast(AgentState, update))

    async def run(self, initial: AgentState) -> AgentState:
        """保留同一消息链补齐缺项，预算和故障交回调用侧处理"""
        state = initial.copy()
        state["messages"] = merge_messages([], initial["messages"])
        try:
            while True:
                self._update(state, await self.model_step(state))
                if state.get("error") or state.get("halted"):
                    return state
                if tool_calls(state):
                    self.end_state.end_requested = False
                    self._update(state, await self.execute_batch(state))
                    if state.get("error") or state.get("halted"):
                        return state
                    if not self.end_state.end_requested:
                        continue
                state["end_signal"] = "finish" if self.end_state.end_requested else "no_tool"
                if self.observer is not None:
                    self.observer.close_turn()
                if self.completion_check is None:
                    state["completion_ok"] = False
                    state["error"] = "未装配 work 完整性检查"
                    return state
                missing = list(self.completion_check())
                state["completion_ok"] = not missing
                state["missing"] = missing
                if not missing:
                    return state
                self.end_state.end_requested = False
                self._update(
                    state,
                    {
                        "messages": [
                            UserMessage(
                                content=(
                                    "程序检查到当前 Agent 仍有缺口，请在同一会话补齐后再次结束：\n"
                                    + "\n".join(f"- {item}" for item in missing)
                                )
                            )
                        ]
                    },
                )
        finally:
            if self.observer is not None:
                self.observer.close_turn()
