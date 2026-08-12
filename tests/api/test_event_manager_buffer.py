"""EventManager 消息缓冲测试：无连接也缓冲、断线保留、重连回放"""

from __future__ import annotations

import asyncio

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


@pytest.mark.asyncio
async def test_send_assigns_monotonic_seq_per_task() -> None:
    """每条消息按 task_id 独立分配从 1 开始的单调递增 seq"""
    manager = EventManager()
    try:
        await manager.send("task-1", "stage_start", {"stage": "annotate"})
        await manager.send("task-1", "llm_output", {"content": "第一段"})
        await manager.send("task-2", "message", {"content": "另一任务"})

        queue1 = await manager.connect("task-1")
        queue2 = await manager.connect("task-2")
        seqs1 = []
        while not queue1.empty():
            seqs1.append((await queue1.get())["seq"])
        seqs2 = []
        while not queue2.empty():
            seqs2.append((await queue2.get())["seq"])

        assert seqs1 == [1, 2]
        assert seqs2 == [1]
    finally:
        manager.reset_for_testing()


@pytest.mark.asyncio
async def test_connect_replays_only_messages_after_last_seq() -> None:
    """last_seq 过滤回放：只回放 seq 大于 last_seq 的消息，且保留原 seq"""
    manager = EventManager()
    try:
        await manager.send("task-1", "message", {"content": "one"})
        await manager.send("task-1", "message", {"content": "two"})
        await manager.send("task-1", "message", {"content": "three"})

        queue = await manager.connect("task-1", last_seq=1)
        messages = []
        while not queue.empty():
            messages.append(await queue.get())
        await manager.disconnect("task-1", queue)

        assert [m["data"]["content"] for m in messages] == ["two", "three"]
        assert [m["seq"] for m in messages] == [2, 3]
    finally:
        manager.reset_for_testing()


@pytest.mark.asyncio
async def test_connect_last_seq_none_replays_everything() -> None:
    """last_seq 缺省时回放全部缓冲消息"""
    manager = EventManager()
    try:
        await manager.send("task-1", "message", {"content": "one"})
        await manager.send("task-1", "message", {"content": "two"})

        queue = await manager.connect("task-1", last_seq=None)
        messages = []
        while not queue.empty():
            messages.append(await queue.get())
        await manager.disconnect("task-1", queue)

        assert [m["data"]["content"] for m in messages] == ["one", "two"]
    finally:
        manager.reset_for_testing()


@pytest.mark.asyncio
async def test_clear_buffer_drops_replayed_events_but_keeps_connection() -> None:
    """clear_buffer 清空缓冲供重连回放，但不影响已连接客户端的实时推送"""
    manager = EventManager()
    try:
        queue = await manager.connect("task-1")
        await manager.send("task-1", "task_complete", {"message": "上一轮完成"})

        manager.clear_buffer("task-1")
        await manager.send("task-1", "stage_start", {"stage": "preprocess"})

        # 已连接客户端实时收到全部消息（清空只影响缓冲回放）
        assert (await queue.get())["type"] == "task_complete"
        assert (await queue.get())["type"] == "stage_start"
        await manager.disconnect("task-1", queue)

        # 重连客户端只回放清空后的事件，上一轮终态不再出现
        queue2 = await manager.connect("task-1")
        messages = []
        while not queue2.empty():
            messages.append(await queue2.get())
        await manager.disconnect("task-1", queue2)

        assert [m["type"] for m in messages] == ["stage_start"]
    finally:
        manager.reset_for_testing()


@pytest.mark.asyncio
async def test_concurrent_connect_and_send_no_duplicate_or_mutation_error() -> None:
    """connect 回放与 send 并发时不得抛 deque 迭代异常，且每条消息恰好投递一次"""
    manager = EventManager()
    try:
        for index in range(5):
            await manager.send("task-1", "message", {"content": f"msg-{index}"})

        async def connect_and_drain(task_id: str) -> list[dict]:
            queue = await manager.connect(task_id)
            messages = []
            while not queue.empty():
                messages.append(await queue.get())
            await manager.disconnect(task_id, queue)
            return messages

        sender = asyncio.create_task(manager.send("task-1", "message", {"content": "mid"}))
        receiver = asyncio.create_task(connect_and_drain("task-1"))
        await sender
        messages = await receiver

        contents = [m["data"]["content"] for m in messages]
        assert contents.count("mid") == 1
        assert len(contents) == len(set(contents))
    finally:
        manager.reset_for_testing()
