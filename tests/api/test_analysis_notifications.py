"""通知持久边界、快照与容量隔离"""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import patch

import pytest

from src.event_bus import EventBus, Message
from src.sse.manager import EventManager
from src.sse.notification_consumer import NotificationConsumer
from src.sse.projection import AnalysisProjection


class DurableMessages:
    def __init__(self):
        self.rows = []
        self.fail = False
        self.lost_receipt = False

    def replay(self, task_id, after_seq):
        return [row for row in self.rows if row["seq"] > after_seq][:128]

    def emit(self, task_id, event_type, data):
        if self.fail:
            raise OSError("消息存储不可用")
        existing = next((row for row in self.rows if row["data"]["message_id"] == data["message_id"]), None)
        if existing:
            return existing
        row = {"type": event_type, "data": data, "seq": len(self.rows) + 1}
        self.rows.append(row)
        if self.lost_receipt:
            self.lost_receipt = False
            raise OSError("提交回执丢失")
        return row


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["task_complete", "task_cancelled", "task_error"])
async def test_close_flushes_accepted_activity_before_terminal(terminal):
    repository = DurableMessages()
    bus, manager = EventBus(), EventManager(outbox=repository)
    consumer = NotificationConsumer(bus, manager)
    try:
        for identity, event_type in (("activity", "llm_output"), ("terminal", terminal)):
            await bus.deliver(Message(topic="analysis.notification", target="notifications", source="workflow",
                run_id="run", message_id=identity,
                payload={"task_id": "task", "type": event_type, "data": {"invocation_id": "agent"}}))
        await consumer.close()
        assert [row["type"] for row in repository.rows] == ["llm_output", terminal]
        assert consumer.pending("task") == 0
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_persistent_write_failure_warns_until_shutdown_deadline_without_acknowledgement():
    repository = DurableMessages()
    repository.fail = True
    bus, manager = EventBus(), EventManager(outbox=repository)
    consumer = NotificationConsumer(bus, manager)
    try:
        with patch("src.sse.notification_consumer.logger.warning") as warning:
            await bus.deliver(Message(topic="analysis.notification", target="notifications", source="workflow",
                run_id="run", message_id="original",
                payload={"task_id": "task", "type": "task_complete", "data": {"status": "completed"}}))
            assert consumer.queues["task"].maxsize == 512
            await asyncio.wait_for(consumer.close(), 7)
        retries = [call for call in warning.call_args_list if "保留原消息重试" in call.args[0]]
        assert len(retries) >= 2
        assert all(call.args[2] == "original" for call in retries)
        assert any("仍有未持久通知" in call.args[0] for call in warning.call_args_list)
        assert repository.rows == []
        assert (await manager.connect_snapshot("task"))[1]["cursor"] == 0
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_failed_write_does_not_publish_or_advance_projection():
    repository = DurableMessages()
    manager = EventManager(outbox=repository)
    queue, snapshot = await manager.connect_snapshot("task")
    repository.fail = True
    try:
        with pytest.raises(OSError):
            await manager.send("task", "task_state", {"message_id": "a", "status": "running"})
        assert queue.empty()
        assert snapshot["cursor"] == 0
        assert (await manager.connect_snapshot("task"))[1]["cursor"] == 0
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_lost_commit_receipt_reuses_original_sequence():
    repository = DurableMessages()
    manager = EventManager(outbox=repository)
    repository.lost_receipt = True
    data = {"message_id": "same", "status": "running"}
    try:
        with pytest.raises(OSError):
            await manager.send("task", "task_state", data)
        await manager.send("task", "task_state", data)
        await manager.send("task", "task_state", data)
        assert len(repository.rows) == 1
        assert (await manager.connect_snapshot("task"))[1]["cursor"] == 1
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_snapshot_replaces_prefix_and_subscription_starts_after_boundary():
    manager = EventManager()
    try:
        await manager.send("task", "llm_output", {"invocation_id": "agent", "content": "前缀"})
        queue, snapshot = await manager.connect_snapshot("task")
        await manager.send("task", "llm_output", {"invocation_id": "agent", "content": "后缀"})
        assert snapshot["executions"]["agent"]["output"] == "前缀"
        assert queue.qsize() == 1
        assert (await queue.get())["seq"] == snapshot["cursor"] + 1
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_consumer_owns_retry_and_keeps_following_message_behind_failure():
    repository = DurableMessages()
    repository.fail = True
    bus, manager = EventBus(), EventManager(outbox=repository)
    consumer = NotificationConsumer(bus, manager)
    try:
        for identity in ("first", "second"):
            await bus.deliver(Message(topic="analysis.notification", target="notifications", source="test",
                run_id="run", message_id=identity,
                payload={"task_id": "task", "type": "task_state", "data": {"status": "running"}}))
        await asyncio.sleep(.03)
        assert consumer.pending("task") == 2
        assert repository.rows == []
        assert "task" in consumer.errors
        repository.fail = False
        await asyncio.wait_for(consumer.drain("task"), 3)
        assert [row["data"]["message_id"] for row in repository.rows] == ["first", "second"]
        assert consumer.pending("task") == 0
        assert not bus._requests
    finally:
        await consumer.close()
        await manager.shutdown()


@pytest.mark.asyncio
async def test_shared_capacity_is_redacted_for_other_tasks_and_release_updates_both():
    bus, manager = EventBus(), EventManager()
    consumer = NotificationConsumer(bus, manager)
    try:
        for run in ("a", "b"):
            await consumer.accept(Message(topic="analysis.notification", source="test", target="notifications",
                run_id=run, payload={"task_id": run, "type": "task_state", "data": {"status": "running"}}))
        capacity = {"models": [{"model_id": "model", "capacity": 20}], "seats": [
            {"model_id": "model", "slot": 0, "reservation_id": "r", "run_id": "a", "work_id": "secret"}]}
        await consumer.capacity_changed(Message(topic="analysis.capacity", source="pool", target="notifications",
            run_id="a", payload=capacity))
        await asyncio.gather(consumer.drain("a"), consumer.drain("b"))
        foreign = (await manager.connect_snapshot("b"))[1]["seats"][0]
        assert foreign["foreign"] and not foreign["work_id"] and not foreign["run_id"]
        await consumer.capacity_changed(Message(topic="analysis.capacity", source="pool", target="notifications",
            run_id="a", payload={**capacity, "seats": []}))
        await asyncio.gather(consumer.drain("a"), consumer.drain("b"))
        assert (await manager.connect_snapshot("a"))[1]["seats"] == []
        assert (await manager.connect_snapshot("b"))[1]["seats"] == []
    finally:
        await consumer.close()
        await manager.shutdown()


def test_parallel_same_role_executions_and_tool_identities_do_not_overwrite():
    projection = AnalysisProjection()
    for i, invocation in enumerate(("first", "second"), 1):
        projection.apply("agent_activity", {"stage": "diagnose", "sub_stage": "case",
            "invocation_id": invocation, "activity": "starting"}, i)
    for seq, call in enumerate(("call-1", "call-2"), 3):
        projection.apply("tool_call", {"invocation_id": "first", "tool_call_id": call,
            "content": "execute_code", "status": "started"}, seq)
    projection.apply("capacity", {"models": [], "seats": []}, 5)
    assert len(projection.executions) == 2
    assert len(projection.executions["first"]["tools"]) == 2


def test_unrecorded_progress_stays_null_and_old_execution_output_is_bounded():
    projection = AnalysisProjection()
    projection.apply("stage_progress", {"stage": "topic-model", "current": None, "total": None}, 1)
    projection.apply("llm_output", {"invocation_id": "agent", "content": "文" * 9000}, 2)
    snapshot = projection.snapshot()
    assert snapshot["stages"]["topic-model"]["steps"]["processing"]["total"] is None
    assert len(snapshot["executions"]["agent"]["output"]) == 8192
    assert snapshot["executions"]["agent"]["truncated"]


@pytest.mark.asyncio
async def test_cold_snapshot_and_concurrent_sender_share_one_cursor_boundary():
    loop = asyncio.get_running_loop()
    reading, release = asyncio.Event(), threading.Event()

    class PausingMessages(DurableMessages):
        def replay(self, task_id, after_seq):
            page = super().replay(task_id, after_seq)
            if after_seq == 0:
                loop.call_soon_threadsafe(reading.set)
                assert release.wait(2)
            return page

    repository = PausingMessages()
    repository.emit("task", "llm_output", {"message_id": "first", "invocation_id": "agent", "content": "前缀"})
    manager = EventManager(outbox=repository)
    connecting = asyncio.create_task(manager.connect_snapshot("task"))
    try:
        await asyncio.wait_for(reading.wait(), 2)
        sending = asyncio.create_task(manager.send("task", "llm_output",
            {"message_id": "second", "invocation_id": "agent", "content": "后缀"}))
        await asyncio.sleep(.01)
        assert not sending.done()
        release.set()
        queue, snapshot = await connecting
        await sending
        assert snapshot["cursor"] == 1
        assert snapshot["executions"]["agent"]["output"] == "前缀"
        assert queue.qsize() == 1
        increment = queue.get_nowait()
        assert increment["seq"] == 2 and increment["data"]["content"] == "后缀"
    finally:
        release.set()
        await connecting
        await manager.shutdown()


@pytest.mark.asyncio
async def test_slow_client_overflow_reconnects_to_complete_confirmed_snapshot():
    manager = EventManager(buffer_size=2)
    try:
        queue, _ = await manager.connect_snapshot("task")
        for content in ("一", "二", "三"):
            await manager.send("task", "llm_output", {"invocation_id": "agent", "content": content})
        control = queue.get_nowait()
        assert control["type"] == "reconnect_required" and "seq" not in control
        reconnected, snapshot = await manager.connect_snapshot("task")
        assert snapshot["cursor"] == 3
        assert snapshot["executions"]["agent"]["output"] == "一二三"
        assert reconnected.empty()
    finally:
        await manager.shutdown()


def test_more_than_128_occupied_workstations_keep_all_active_executions():
    projection = AnalysisProjection()
    projection.apply("capacity", {"seats": [
        {"reservation_id": f"seat-{i}"} for i in range(130)
    ]}, 1)
    for i in range(130):
        projection.apply("agent_activity", {"invocation_id": f"agent-{i}",
            "reservation_id": f"seat-{i}", "activity": "starting"}, i + 2)
    assert len(projection.snapshot()["executions"]) == 130
