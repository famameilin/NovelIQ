"""工作流经总线接管通知，快照与后续原始消息共同形成执行画面"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.api.routes.sse import sse_endpoint
from src.event_bus import EventBus
from src.event_bus.notifications import StreamEvent
from src.sse.manager import EventManager
from src.sse.notification_consumer import NotificationConsumer
from src.workflows.progress import AnalysisEventBus


@pytest.mark.asyncio
async def test_workflow_bus_consumer_snapshot_then_increment_and_terminal(monkeypatch):
    bus, manager = EventBus(), EventManager()
    consumer = NotificationConsumer(bus, manager)
    monkeypatch.setattr("src.api.routes.sse.event_manager", manager)
    monkeypatch.setattr(
        "src.api.routes.sse._task_run_belongs_to_novel", lambda *_: {"run_id": "run", "status": "running"}
    )
    notifier = AnalysisEventBus("task", run_id="run", bus=bus)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(notifications=consumer)),
        is_disconnected=AsyncMock(side_effect=[False] * 7 + [True]))
    try:
        await notifier.emit(StreamEvent(action="stage_state", stage="annotate", status="running"))
        await notifier.emit(StreamEvent(action="output", invocation_id="agent", stream_id="stream", content="前缀"))
        await consumer.drain("task")
        response = await sse_endpoint("novel", "task", request)
        await notifier.emit(StreamEvent(action="thinking", invocation_id="agent", stream_id="stream", content="推理"))
        await notifier.emit(StreamEvent(action="output", invocation_id="agent", stream_id="stream", content="后缀"))
        await notifier.emit(StreamEvent(action="activity", invocation_id="agent", activity="saving"))
        await notifier.emit(StreamEvent(action="work_saved", invocation_id="agent"))
        await notifier.emit_task_complete()
        await consumer.drain("task")
        chunks = [chunk async for chunk in response.body_iterator]
        snapshot = json.loads(chunks[0]["data"])
        assert snapshot["executions"]["agent"]["output"] == "前缀"
        assert snapshot["stage"] == "annotate"
        increments = [chunk for chunk in chunks[1:] if "id" in chunk]
        assert len({chunk["id"] for chunk in increments}) == len(increments)
        assert [chunk["event"] for chunk in increments][-3:] == ["agent_activity", "work_saved", "task_complete"]
        final = (await manager.connect_snapshot("task"))[1]
        assert final["executions"]["agent"]["output"] == "前缀后缀"
        assert final["executions"]["agent"]["thinking"] == "推理"
        assert final["executions"]["agent"]["activity"] == "saved"
        assert final["status"] == "completed"
        assert not bus._requests
    finally:
        await consumer.close()
        await manager.shutdown()
