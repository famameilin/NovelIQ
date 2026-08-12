"""
SSE 路由测试

覆盖 src/api/routes/sse.py 的 sse_endpoint：
- 事件透传（type -> event 字段、data -> JSON 字符串）
- 消息缺省字段时的默认值
- 客户端断开时的清理（disconnect 调用）

2026-08-12 创建，补齐 SSE 路由零覆盖缺口。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.routes.sse import sse_endpoint


def _make_request(disconnect_flags: list[bool]) -> MagicMock:
    """构造请求 mock：is_disconnected 依次返回给定结果后保持最后值"""
    request = MagicMock()
    request.is_disconnected = AsyncMock(side_effect=disconnect_flags)
    return request


@pytest.mark.asyncio
async def test_sse_streams_events_with_type_and_data() -> None:
    queue: asyncio.Queue[dict] = asyncio.Queue()
    queue.put_nowait({"type": "progress", "data": {"sub_percent": 25}})
    queue.put_nowait({"type": "complete", "data": {"status": "ok"}})

    mock_em = MagicMock()
    mock_em.connect = AsyncMock(return_value=queue)
    mock_em.disconnect = AsyncMock()

    request = _make_request([False, False, True])
    with patch("src.api.routes.sse.event_manager", mock_em):
        response = await sse_endpoint("task-1", request)
        chunks = [chunk async for chunk in response.body_iterator]

    assert [chunk["event"] for chunk in chunks] == ["progress", "complete"]
    assert chunks[0]["data"] == '{"sub_percent": 25}'
    assert chunks[1]["data"] == '{"status": "ok"}'
    mock_em.connect.assert_awaited_once_with("task-1")
    mock_em.disconnect.assert_awaited_once_with("task-1", queue)


@pytest.mark.asyncio
async def test_sse_defaults_when_message_lacks_type_and_data() -> None:
    queue: asyncio.Queue[dict] = asyncio.Queue()
    queue.put_nowait({"reason": "no type field"})

    mock_em = MagicMock()
    mock_em.connect = AsyncMock(return_value=queue)
    mock_em.disconnect = AsyncMock()

    request = _make_request([False, True])
    with patch("src.api.routes.sse.event_manager", mock_em):
        response = await sse_endpoint("task-1", request)
        chunks = [chunk async for chunk in response.body_iterator]

    assert chunks[0]["event"] == "message"
    assert chunks[0]["data"] == "{}"
    mock_em.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_sse_disconnects_cleanly_when_client_disconnects() -> None:
    queue: asyncio.Queue[dict] = asyncio.Queue()

    mock_em = MagicMock()
    mock_em.connect = AsyncMock(return_value=queue)
    mock_em.disconnect = AsyncMock()

    request = _make_request([True])
    with patch("src.api.routes.sse.event_manager", mock_em):
        response = await sse_endpoint("task-1", request)
        chunks = [chunk async for chunk in response.body_iterator]

    assert chunks == []
    mock_em.connect.assert_awaited_once_with("task-1")
    mock_em.disconnect.assert_awaited_once_with("task-1", queue)
