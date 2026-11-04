"""标注会话的模型循环与逐调用业务执行装配"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.agents.loop import AgentLoop
from src.agents.model_step import build_model_step

from .ledger import AnnotationToolLedger
from .tool_batch import _build_tool_batch_node

if TYPE_CHECKING:
    from src.agents.stream import AgentStream
    from src.agents.turn_observer import AgentTurnObserver


def build_agent_loop(
    llm: Any,
    program_tool: Any,
    finish_tool: Any,
    *,
    ledger: AnnotationToolLedger,
    max_iterations: int,
    context_window_tokens: int | None = None,
    stream: AgentStream | None = None,
    observer: AgentTurnObserver | None = None,
    retries: int | None = None,
    completion_check: Callable[[], list[str]] | None = None,
    thinking_message: Callable[[int], str] | None = None,
) -> AgentLoop:
    """绑定程序与结束入口，领域写入继续由现有账本维护"""
    tools = [program_tool, finish_tool]
    return AgentLoop(
        build_model_step(
            llm,
            tools,
            context_summary=ledger.context_summary,
            before_round=lambda state: ledger.set_phase(state.get("phase", ledger.phase)),
            max_iterations=max_iterations,
            context_window_tokens=context_window_tokens,
            stream=stream,
            observer=observer,
            retries=retries,
            thinking_message=thinking_message,
        ),
        _build_tool_batch_node(
            tools,
            ledger=ledger,
            observer=observer,
            stream=stream,
            program_tool_name=str(program_tool.name),
        ),
        end_state=ledger,
        completion_check=completion_check,
        observer=observer,
    )
