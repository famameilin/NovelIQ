"任务状态与模型通信事件出口"

from __future__ import annotations

from src.sse.events import StreamEvent, StreamMessageType
from src.work.task_manager import TaskManager

__all__ = ["AnalysisEventBus", "StreamEvent", "StreamMessageType"]


_ACTION_TO_SSE_EVENT = {"output": "llm_output", "thinking": "llm_thinking", "tool_call": "tool_call"}


class AnalysisEventBus:
    """发送任务终态与模型通信，并缓存模型输出"""

    def __init__(self, task_id: str, task_manager: TaskManager) -> None:
        self.task_id = task_id
        self.task_manager = task_manager

    async def emit(self, event: StreamEvent) -> None:
        "发送模型通信，不保存运行进度"
        if event.action not in {"output", "thinking", "tool_call"}:
            return
        from src.sse.manager import event_manager

        data = {
            key: value
            for key, value in event.to_dict().items()
            if key not in {"stage", "sub_stage", "current", "total", "percent", "sub_percent"}
        }
        data["agent_type"] = event.sub_stage
        await event_manager.send(task_id=self.task_id, event_type=_ACTION_TO_SSE_EVENT[event.action], data=data)
        if event.action == "output":
            self.task_manager.append_llm_output(self.task_id, event.content)

    # 阶段级事件

    async def emit_task_complete(self) -> None:
        """发送任务完成事件（使用 task_complete SSE 事件类型）"""
        from src.sse.manager import event_manager

        await event_manager.send(
            task_id=self.task_id,
            event_type=StreamMessageType.task_complete.value,
            data={"status": "completed"},
        )

    async def emit_task_error(self, error: str, stage: str = "failed") -> None:
        """发送任务错误事件"""
        from src.sse.manager import event_manager

        await event_manager.send(
            task_id=self.task_id,
            event_type=StreamMessageType.task_error.value,
            data={"status": "failed"},
        )

    async def emit_task_cancelled(self) -> None:
        """发送任务取消事件"""
        from src.sse.manager import event_manager

        await event_manager.send(
            task_id=self.task_id,
            event_type=StreamMessageType.task_cancelled.value,
            data={"status": "cancelled"},
        )
