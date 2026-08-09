"""EventManager 消息缓冲测试：无连接也缓冲、断线保留、重连回放"""

from __future__ import annotations

import pytest

from src.api.services.event_manager import EventManager


@pytest.mark.asyncio
async def test_send_before_connect_is_buffered_and_replayed() -> None:
    """连接建立前发送的事件必须入缓冲，late-joiner 可回放"""
    manager = EventManager()
    try:
        await manager.send("task-1", "stage_start", {"stage": "annotate"})
        await manager.send("task-1", "llm_output", {"content": "你好"})

        queue = await manager.connect("task-1")
        messages = []
        while not queue.empty():
            messages.append(await queue.get())

        assert [m["type"] for m in messages] == ["stage_start", "llm_output"]
        assert messages[1]["data"]["content"] == "你好"
    finally:
        manager.reset_for_testing()


@pytest.mark.asyncio
async def test_disconnect_keeps_buffer_for_reconnect() -> None:
    """断线后缓冲必须保留，重连客户端仍能回放断线窗口期事件"""
    manager = EventManager()
    try:
        queue1 = await manager.connect("task-1")
        await manager.send("task-1", "llm_output", {"content": "第一段"})
        await manager.disconnect("task-1", queue1)

        await manager.send("task-1", "llm_output", {"content": "第二段"})

        queue2 = await manager.connect("task-1")
        messages = []
        while not queue2.empty():
            messages.append(await queue2.get())
        await manager.disconnect("task-1", queue2)

        contents = [m["data"]["content"] for m in messages]
        assert contents == ["第一段", "第二段"]
    finally:
        manager.reset_for_testing()


@pytest.mark.asyncio
async def test_buffer_respects_maxlen() -> None:
    """环形缓冲超过上限时淘汰最旧消息"""
    manager = EventManager(buffer_size=3)
    try:
        for index in range(5):
            await manager.send("task-1", "message", {"content": f"msg-{index}"})

        queue = await manager.connect("task-1")
        messages = []
        while not queue.empty():
            messages.append(await queue.get())

        assert [m["data"]["content"] for m in messages] == ["msg-2", "msg-3", "msg-4"]
    finally:
        manager.reset_for_testing()


@pytest.mark.asyncio
async def test_connect_replays_buffer_only_after_first_connect() -> None:
    """首次 connect 前无缓冲则回放为空，随后的事件正常入缓冲"""
    manager = EventManager()
    try:
        queue = await manager.connect("task-1")
        assert queue.empty()

        await manager.send("task-1", "llm_output", {"content": "事件"})
        assert not queue.empty()
        message = await queue.get()
        assert message["type"] == "llm_output"
        await manager.disconnect("task-1", queue)
    finally:
        manager.reset_for_testing()
