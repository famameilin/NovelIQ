"""把工作流事实交付消息总线，不直接调用 SSE 管理器"""

from __future__ import annotations

from uuid import uuid4

from src.event_bus import EVENT_BUS, EventBus, Message
from src.event_bus.notifications import StreamEvent

_ACTIONS = {
    "output": "llm_output",
    "thinking": "llm_thinking",
    "tool_call": "tool_call",
    "work_reset": "work_reset",
    "work_saved": "work_saved",
    "chapter_reset": "chapter_reset",
    "activity": "agent_activity",
    "stage_state": "stage_state",
    "progress": "stage_progress",
}


class AnalysisEventBus:
    def __init__(self, task_id: str, *, run_id: str = "", bus: EventBus = EVENT_BUS):
        self.task_id, self.run_id, self.bus = task_id, run_id, bus

    async def notify(self, event_type: str, data: dict) -> None:
        await self.bus.deliver(
            Message(
                topic="analysis.notification",
                source="workflow",
                target="notifications",
                run_id=self.run_id,
                message_id=data.get("message_id") or uuid4().hex,
                payload={"task_id": self.task_id, "type": event_type, "data": data},
            )
        )

    async def emit(self, event: StreamEvent) -> None:
        data = event.to_dict()
        data["run_id"] = self.run_id
        data["agent_type"] = event.sub_stage
        if event.action in {"start", "complete"}:
            if event.sub_stage:
                data["status"] = "completed" if event.action == "complete" else "running"
                await self.notify("stage_progress", data)
            return
        await self.notify(_ACTIONS.get(event.action, event.action), data)

    async def emit_task_complete(self) -> None:
        await self.notify("task_complete", {"status": "completed"})

    async def emit_task_error(self, error: str, stage: str = "failed") -> None:
        await self.notify("task_error", {"status": "failed", "error": error, "stage": stage})

    async def emit_task_cancelled(self) -> None:
        await self.notify("task_cancelled", {"status": "cancelled"})
