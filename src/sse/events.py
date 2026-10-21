"""SSE 线上事件名与中立通知导出"""

from enum import StrEnum

from src.event_bus.notifications import StreamEvent, StreamEventAction

__all__ = ["StreamEvent", "StreamEventAction", "StreamMessageType"]

class StreamMessageType(StrEnum):
    """流式消息类型枚举（SSE 线上事件名）"""

    llm_output = "llm_output"
    llm_thinking = "llm_thinking"
    tool_call = "tool_call"
    task_complete = "task_complete"
    task_error = "task_error"
    task_cancelled = "task_cancelled"
