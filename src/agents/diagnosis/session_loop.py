"""诊断程序与领域完成检查的会话装配"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.agents.annotation.tool_batch import _build_tool_batch_node
from src.agents.loop import AgentLoop, SessionControl
from src.agents.model_step import build_model_step
from src.agents.tools import Tool

from .program_runtime import DiagnosisProgramRuntime

if TYPE_CHECKING:
    from src.agents.stream import AgentStream
    from src.agents.turn_observer import AgentTurnObserver


def build_diagnosis_loop(
    llm: Any,
    runtime: DiagnosisProgramRuntime,
    *,
    max_iterations: int,
    completion_check: Callable[[], list[str]] | None,
    context_window_tokens: int | None = None,
    stream: AgentStream | None = None,
    observer: AgentTurnObserver | None = None,
    retries: int | None = None,
) -> AgentLoop:
    """程序成功后提升结束意图，外层 finish 只请求完整性检查"""
    control = SessionControl()
    program = runtime.build_tool()
    finish = runtime.tools["finish"]

    async def execute(code: str) -> str:
        result = await runtime.execute(code)
        control.end_requested = runtime.take_end_request() or control.end_requested
        return result

    async def request_end() -> str:
        result = await finish.ainvoke({})
        control.end_requested = True
        return str(result)

    program.coroutine = execute
    finish_request = Tool.from_function(coroutine=request_end, name=finish.name, description=finish.description)
    tools = [program, finish_request]
    return AgentLoop(
        build_model_step(
            llm,
            tools,
            context_summary=lambda: {},
            max_iterations=max_iterations,
            context_window_tokens=context_window_tokens,
            stream=stream,
            observer=observer,
            retries=retries,
            thinking_message=lambda rounds: f"诊断推理中（第 {rounds} 轮）...",
        ),
        _build_tool_batch_node(
            tools,
            ledger=None,
            observer=observer,
            stream=stream,
            program_tool_name=program.name,
        ),
        end_state=control,
        completion_check=completion_check,
        observer=observer,
    )
