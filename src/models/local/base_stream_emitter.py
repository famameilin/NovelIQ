"""
BaseModelClient 流式缓冲与事件发送辅助模块。

创建时间: 2026-04-23
任务: p2-base-model-client-split
说明: 从 base.py 中拆出流式 chunk 聚合、节流发送与响应对象拼装逻辑，
      让 BaseModelClient 只保留兼容入口与运行时上下文。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.api.models.events import StreamEvent


@dataclass
class StreamAggregationState:
    """
    流式响应聚合状态。

    创建时间: 2026-04-23
    任务: p2-base-model-client-split
    新建原因: 将 output/thinking 缓冲、节流时钟与 usage 聚合从 transport 主循环中拆出。
    """

    content_chunks: list[str] = field(default_factory=list)
    reasoning_chunks: list[str] = field(default_factory=list)
    chunk_count: int = 0
    usage: Any = None
    last_output_broadcast_time: float = 0.0
    output_buffer: str = ""
    output_char_count: int = 0
    last_thinking_broadcast_time: float = 0.0
    thinking_buffer: str = ""
    thinking_char_count: int = 0


async def emit_stream_delta(
    state: StreamAggregationState,
    delta: Any,
    *,
    is_cloud: bool,
    emitter: Any,
) -> None:
    """
    处理单个流式 delta，并按节流策略发送 SSE 事件。

    创建时间: 2026-04-23
    任务: p2-base-model-client-split
    新建原因: 统一 output/thinking 两类缓冲逻辑，减少 transport 中的重复 if 分支。
    """
    content = getattr(delta, "content", None)
    if content:
        state.content_chunks.append(content)
        state.output_buffer += content
        state.output_char_count += len(content)

        if is_cloud:
            print(content, end="", flush=True)

        current_time = time.time()
        should_broadcast = current_time - state.last_output_broadcast_time >= 0.1 or state.output_char_count >= 50
        if emitter and should_broadcast:
            from src.api.models.events import StreamEvent

            await emitter(StreamEvent(action="output", content=state.output_buffer))
            state.output_buffer = ""
            state.output_char_count = 0
            state.last_output_broadcast_time = current_time

    reasoning_content = getattr(delta, "reasoning_content", None)
    if reasoning_content:
        state.reasoning_chunks.append(reasoning_content)
        state.thinking_buffer += reasoning_content
        state.thinking_char_count += len(reasoning_content)

        if is_cloud:
            print(f"\033[90m{reasoning_content}\033[0m", end="", flush=True)

        current_time = time.time()
        should_broadcast = current_time - state.last_thinking_broadcast_time >= 0.1 or state.thinking_char_count >= 50
        if emitter and should_broadcast:
            from src.api.models.events import StreamEvent

            await emitter(StreamEvent(action="thinking", content=state.thinking_buffer))
            state.thinking_buffer = ""
            state.thinking_char_count = 0
            state.last_thinking_broadcast_time = current_time


async def flush_stream_buffers(state: StreamAggregationState, emitter: Any) -> None:
    """
    发送流末尾尚未广播的残余缓冲。

    创建时间: 2026-04-23
    任务: p2-base-model-client-split
    新建原因: 保证 transport 在循环结束后只关心"收尾"，不重复关心两类 buffer 细节。
    """
    from src.api.models.events import StreamEvent

    if emitter and state.output_buffer:
        await emitter(StreamEvent(action="output", content=state.output_buffer))
    if emitter and state.thinking_buffer:
        await emitter(StreamEvent(action="thinking", content=state.thinking_buffer))


def finalize_stream_content(state: StreamAggregationState) -> tuple[str, str | None]:
    """
    将聚合状态收束为最终 content/reasoning_content。

    创建时间: 2026-04-23
    任务: p2-base-model-client-split
    新建原因: 统一处理“只有 thinking 没有正文”的兼容回退。
    """
    full_content = "".join(state.content_chunks)
    full_reasoning = "".join(state.reasoning_chunks) if state.reasoning_chunks else None

    if not full_content and full_reasoning:
        full_content = full_reasoning
        full_reasoning = None

    return full_content, full_reasoning


def build_stream_response(
    model_name: str | None,
    content: str,
    reasoning_content: str | None,
    usage: Any = None,
) -> Any:
    """
    将流式内容拼装成与非流式一致的响应对象。

    创建时间: 2026-04-23
    任务: p2-base-model-client-split
    新建原因: 让 transport 与 BaseModelClient 都复用同一份响应构造逻辑。
    """
    message = SimpleNamespace(
        content=content,
        reasoning_content=reasoning_content,
        role="assistant",
    )
    choice = SimpleNamespace(
        message=message,
        finish_reason="stop",
        index=0,
    )
    return SimpleNamespace(
        choices=[choice],
        model=model_name,
        usage=usage,
    )
