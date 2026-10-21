"""SSE 快照边界、增量、同步告警与所有权守卫"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from src.api.routes.sse import sse_endpoint
from src.sse.projection import AnalysisProjection


def request(flags):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(notifications=None)),
        is_disconnected=AsyncMock(side_effect=flags),
        headers={"last-event-id": "900"},
        query_params={"last_seq": "800"},
    )


def manager_with(queue):
    manager = MagicMock()
    manager.connect_snapshot = AsyncMock(return_value=(queue, AnalysisProjection().snapshot()))
    manager.disconnect = AsyncMock()
    manager.replay = AsyncMock(return_value=[])
    return manager


@pytest.mark.asyncio
async def test_snapshot_precedes_increments_and_cursor_comes_from_persisted_boundary():
    queue = asyncio.Queue()
    queue.put_nowait({"type": "stage_progress", "data": {"current": 25}, "seq": 1})
    queue.put_nowait({"type": "task_complete", "data": {"status": "completed"}, "seq": 2})
    manager = manager_with(queue)
    with (
        patch("src.api.routes.sse._task_run_belongs_to_novel", return_value={"run_id": "run"}),
        patch("src.api.routes.sse.event_manager", manager),
    ):
        response = await sse_endpoint("novel", "task", request([False, False, True]))
        chunks = [chunk async for chunk in response.body_iterator]
    durable = [chunk for chunk in chunks if "id" in chunk]
    assert [chunk["event"] for chunk in durable] == ["snapshot", "stage_progress", "task_complete"]
    assert [chunk["id"] for chunk in durable] == ["0", "1", "2"]
    assert json.loads(durable[1]["data"]) == {"current": 25}
    controls = [json.loads(chunk["data"]) for chunk in chunks if chunk["event"] == "notification_status"]
    assert controls[0]["sync_pending"] is True
    assert controls[-1]["sync_pending"] is False
    manager.connect_snapshot.assert_awaited_once_with("task")
    manager.disconnect.assert_awaited_once_with("task", queue)


@pytest.mark.asyncio
async def test_disconnect_after_snapshot_cleans_up_own_subscription():
    queue = asyncio.Queue()
    manager = manager_with(queue)
    with (
        patch("src.api.routes.sse._task_run_belongs_to_novel", return_value={"run_id": "run"}),
        patch("src.api.routes.sse.event_manager", manager),
    ):
        response = await sse_endpoint("novel", "task", request([True]))
        chunks = [chunk async for chunk in response.body_iterator]
    assert chunks[0]["event"] == "snapshot"
    manager.disconnect.assert_awaited_once_with("task", queue)


@pytest.mark.asyncio
async def test_slow_client_receives_reconnect_control_without_advancing_cursor():
    queue = asyncio.Queue()
    queue.put_nowait({"type": "reconnect_required", "data": {"reason": "backpressure"}})
    manager = manager_with(queue)
    with (
        patch("src.api.routes.sse._task_run_belongs_to_novel", return_value={"run_id": "run"}),
        patch("src.api.routes.sse.event_manager", manager),
    ):
        response = await sse_endpoint("novel", "task", request([False]))
        chunks = [chunk async for chunk in response.body_iterator]
    assert chunks[-1]["event"] == "reconnect_required" and "id" not in chunks[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize("novel", ["missing", "another-novel"])
async def test_missing_or_foreign_task_does_not_create_subscription(novel):
    with (
        patch("src.api.routes.sse._task_run_belongs_to_novel", return_value=None),
        patch("src.api.routes.sse.event_manager") as manager,
    ):
        with pytest.raises(HTTPException) as caught:
            await sse_endpoint(novel, "task", request([True]))
    assert caught.value.status_code == 404
    manager.connect_snapshot.assert_not_called()
