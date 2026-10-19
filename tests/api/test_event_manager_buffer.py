"""EventManager 消息缓冲测试：无连接也缓冲、断线保留、重连回放"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select

from src.sse.manager import EventManager
from tests.support.storage_fixtures import fixture_id, storage_factory, task_for_run


def _persisted_message_count(db_session, run_id: str) -> int:
    """按真实路由列统计 run 内已保存的展示消息（run 归属在 agent_outbox 宽行）"""
    from src.storage.models import EventOutbox

    return int(
        db_session.execute(
            select(func.count()).select_from(EventOutbox).where(EventOutbox.run_id == run_id)
        ).scalar_one()
    )


@pytest.mark.asyncio
async def test_default_buffer_holds_recent_256_messages() -> None:
    """默认缓冲从 64 提升到 256，断线窗口期消息更不易被淘汰"""
    manager = EventManager()
    try:
        assert manager._buffer_size == 256
        for index in range(300):
            await manager.send("task-1", "message", {"content": f"msg-{index}"})

        queue = await manager.connect("task-1")
        messages = []
        while not queue.empty():
            messages.append(await queue.get())
        await manager.disconnect("task-1", queue)

        assert len(messages) == 256
        assert messages[0]["data"]["content"] == "msg-44"
        assert messages[-1]["data"]["content"] == "msg-299"
    finally:
        manager.reset_for_testing()


@pytest.mark.asyncio
async def test_send_before_connect_is_buffered_and_replayed() -> None:
    """连接建立前发送的事件必须入缓冲，late-joiner 可回放"""
    manager = EventManager()
    try:
        await manager.send("task-1", "llm_thinking", {"stage": "annotate"})
        await manager.send("task-1", "llm_output", {"content": "你好"})

        queue = await manager.connect("task-1")
        messages = []
        while not queue.empty():
            messages.append(await queue.get())

        assert [m["type"] for m in messages] == ["llm_thinking", "llm_output"]
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
        await manager.send("task-1", "llm_thinking", {"stage": "annotate"})
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
        await manager.send("task-1", "llm_thinking", {"stage": "preprocess"})

        # 已连接客户端实时收到全部消息（清空只影响缓冲回放）
        assert (await queue.get())["type"] == "task_complete"
        assert (await queue.get())["type"] == "llm_thinking"
        await manager.disconnect("task-1", queue)

        # 重连客户端只回放清空后的事件，上一轮终态不再出现
        queue2 = await manager.connect("task-1")
        messages = []
        while not queue2.empty():
            messages.append(await queue2.get())
        await manager.disconnect("task-1", queue2)

        assert [m["type"] for m in messages] == ["llm_thinking"]
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


@pytest.mark.asyncio
async def test_failed_persistence_replays_actual_cache_with_same_cursor_and_identity():
    class DelayedOutbox:
        def __init__(self):
            self.rows = []
            self.failed = True

        def reserve_sequence(self, task_id, message_id):
            return 41

        def display_state(self, task_id):
            from src.sse.state import DisplayState

            return DisplayState()

        def emit(self, task_id, event_type, data, *, sequence):
            if self.failed:
                raise RuntimeError("保存延迟")
            if not self.rows:
                self.rows.append({"seq": sequence, "type": event_type, "data": data})

        def replay(self, task_id, after_seq):
            return [row for row in self.rows if row["seq"] > after_seq]

    manager = EventManager()
    outbox = DelayedOutbox()
    manager.configure_outbox(outbox)
    data = {"message_id": "actual-message", "invocation_id": fixture_id(__name__, "current-inv"), "content": "实际输出"}
    try:
        with pytest.raises(RuntimeError, match="保存延迟"):
            await manager.send("task", "llm_output", data)
        assert (await manager.replay("task", 0))[0]["seq"] == 41
        outbox.failed = False
        await manager.send("task", "llm_output", data)
        await manager.send("task", "llm_output", data)
        replay = await manager.replay("task", 0)
        assert len(replay) == 1 and replay[0]["data"] == data
        assert await manager.replay("task", 41) == []
    finally:
        manager.reset_for_testing()


@pytest.mark.asyncio
async def test_replay_short_page_and_concurrent_send_keep_all_persisted_sequences():
    """短页查询期间发送超过缓存容量，客户端仍能逐页收到全部持久消息"""
    from copy import deepcopy

    from src.sse.state import DisplayState

    class ConcurrentOutbox:
        def __init__(self):
            self.rows = []
            self.seq = 0
            self.loop = asyncio.get_running_loop()
            self.ready = asyncio.Event()
            self.release = asyncio.Event()
            self.sent_during_snapshot = asyncio.Event()
            self.querying = False

        def display_state(self, task_id):
            return DisplayState()

        def reserve_sequence(self, task_id, message_id):
            if self.querying:
                self.loop.call_soon_threadsafe(self.sent_during_snapshot.set)
            self.seq += 1
            return self.seq

        def emit(self, task_id, event_type, data, *, sequence):
            self.rows.append({"type": event_type, "data": deepcopy(data), "seq": sequence})

        def replay(self, task_id, after_seq):
            snapshot = [deepcopy(row) for row in self.rows if row["seq"] > after_seq][:128]
            self.querying = True
            self.loop.call_soon_threadsafe(self.ready.set)
            asyncio.run_coroutine_threadsafe(self.release.wait(), self.loop).result()
            self.querying = False
            return snapshot

    outbox = ConcurrentOutbox()
    manager = EventManager()
    manager.configure_outbox(outbox)

    async def send_many():
        for index in range(400):
            await manager.send("task", "llm_output", {"content": f"new-{index}"})

    sender = None
    pending = None
    try:
        for index in range(10):
            await manager.send("task", "llm_output", {"content": f"initial-{index}"})
        pending = asyncio.create_task(manager.replay("task", 0))
        await asyncio.wait_for(outbox.ready.wait(), timeout=1)
        sender = asyncio.create_task(send_many())
        # 查询未完成前不能产生比该持久页更晚的缓存消息
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(outbox.sent_during_snapshot.wait(), timeout=0.05)
        outbox.release.set()
        messages = await pending
        await sender
        while page := await manager.replay("task", messages[-1]["seq"]):
            messages.extend(page)
        assert [message["seq"] for message in messages] == list(range(1, 411))
    finally:
        outbox.release.set()
        if pending is not None:
            await pending
        if sender is not None:
            await sender
        manager.reset_for_testing()


@pytest.mark.asyncio
async def test_postgres_outbox_keeps_generated_sequence_across_reversed_save_and_restart(db_session):
    from src.sse.persistence import SseMessageRepository
    from src.storage.db import get_session_factory
    from tests.support.chapter_annotation_helpers import create_run_with_chunks

    _novel, run_id = create_run_with_chunks(db_session, texts=["原文。"])
    task_id = task_for_run(run_id, db_session)
    outbox = SseMessageRepository(storage_factory(get_session_factory()))
    first = {"message_id": "first:" + run_id, "invocation_id": fixture_id(__name__, "actual-inv"), "content": "先产生"}
    second = {
        "message_id": "second:" + run_id,
        "invocation_id": fixture_id(__name__, "actual-inv"),
        "content": "后产生",
    }
    a = outbox.reserve_sequence(task_id, first["message_id"])
    b = outbox.reserve_sequence(task_id, second["message_id"])
    assert a < b
    outbox.emit(task_id, "llm_output", second, sequence=b)
    outbox.emit(task_id, "llm_output", first, sequence=a)
    manager = EventManager(outbox=outbox)
    try:
        assert [row["seq"] for row in await manager.replay(task_id, 0)] == [a, b]
        await manager.send(task_id, "llm_output", first)
        await manager.send(task_id, "llm_output", first)
        assert [row["seq"] for row in await manager.replay(task_id, 0)] == [a, b]
        assert _persisted_message_count(db_session, run_id) == 2
    finally:
        manager.reset_for_testing()


@pytest.mark.asyncio
async def test_resume_preserves_saved_work_display_but_filters_persisted_old_terminal(db_session):
    from src.sse.persistence import SseMessageRepository
    from src.storage.db import get_session_factory
    from tests.support.chapter_annotation_helpers import create_run_with_chunks

    _novel, run_id = create_run_with_chunks(db_session, texts=["第一章原文。", "第二章原文。"], chapter_ids=[1, 2])
    task_id = task_for_run(run_id, db_session)
    outbox = SseMessageRepository(storage_factory(get_session_factory()))
    manager = EventManager(outbox=outbox)
    completed = {
        "invocation_id": fixture_id(__name__, "complete-inv"),
        "stage": "annotate",
        "chapter_id": 1,
        "sub_stage": "annotation",
    }
    try:
        await manager.send(task_id, "work_reset", {**completed, "message_id": "reset-complete:" + run_id})
        await manager.send(
            task_id,
            "llm_output",
            {
                **completed,
                "message_id": "shown-complete:" + run_id,
                "stream_id": "complete-inv",
                "content": "保留完成章",
            },
        )
        await manager.send(task_id, "task_cancelled", {"message_id": "old-stop:" + run_id})
        await manager.restart_display(task_id)
        await manager.send(task_id, "llm_thinking", {"message_id": "new-stage:" + run_id, "stage": "annotate"})
        restarted = EventManager(outbox=outbox)
        try:
            replay = await restarted.replay(task_id, 0)
            assert "task_cancelled" not in {message["type"] for message in replay}
            output = next(message for message in replay if message["type"] == "llm_output")
            assert output["data"]["content"] == "保留完成章"
            assert replay[-1]["type"] == "llm_thinking"
        finally:
            restarted.reset_for_testing()
    finally:
        manager.reset_for_testing()


@pytest.mark.asyncio
async def test_reset_filters_old_invocation_after_restart_without_deleting_message_history(db_session):
    from src.sse.persistence import SseMessageRepository
    from src.storage.db import get_session_factory
    from tests.support.chapter_annotation_helpers import create_run_with_chunks

    _novel, run_id = create_run_with_chunks(db_session, texts=["原文。"])
    task_id = task_for_run(run_id, db_session)
    outbox = SseMessageRepository(storage_factory(get_session_factory()))
    manager = EventManager(outbox=outbox)
    base = {"stage": "annotate", "sub_stage": "event", "chapter_id": 1}
    try:
        await manager.send(
            task_id,
            "work_reset",
            {**base, "invocation_id": fixture_id(__name__, "old"), "message_id": "old-reset:" + run_id},
        )
        await manager.send(
            task_id,
            "llm_output",
            {
                **base,
                "invocation_id": fixture_id(__name__, "old"),
                "message_id": "old-output:" + run_id,
                "content": "旧执行",
            },
        )
        await manager.send(
            task_id,
            "work_reset",
            {**base, "invocation_id": fixture_id(__name__, "new"), "message_id": "new-reset:" + run_id},
        )
        await manager.send(
            task_id,
            "llm_output",
            {
                **base,
                "invocation_id": fixture_id(__name__, "new"),
                "message_id": "new-output:" + run_id,
                "content": "新执行",
            },
        )
        restarted = EventManager(outbox=outbox)
        try:
            await restarted.send(
                task_id,
                "llm_output",
                {
                    **base,
                    "invocation_id": fixture_id(__name__, "old"),
                    "message_id": "late:" + run_id,
                    "content": "迟到旧执行",
                },
            )
            await restarted.send(
                task_id,
                "work_reset",
                {**base, "invocation_id": fixture_id(__name__, "old"), "message_id": "late-reset:" + run_id},
            )
            replay = await restarted.replay(task_id, 0)
            assert [message["data"]["invocation_id"] for message in replay] == [
                fixture_id(__name__, "new"),
                fixture_id(__name__, "new"),
            ]
            assert _persisted_message_count(db_session, run_id) == 4
        finally:
            restarted.reset_for_testing()
    finally:
        manager.reset_for_testing()


@pytest.mark.asyncio
async def test_sse_module_ignores_old_execution_and_retired_reset():
    from src.event_bus import EventBus, Message
    from src.sse.consumer import SSEModule
    from src.sse.events import StreamEvent

    bus = EventBus()
    shown = []

    async def emit(event):
        shown.append(event)

    module = SSEModule(bus, "run", emit)

    async def send(action, invocation, content=""):
        await module.show(
            Message(
                "sse.show",
                "agent",
                module.address,
                "run",
                "work",
                invocation,
                payload=StreamEvent(
                    action=action, sub_stage="event", chapter_id=1, stream_id=invocation, content=content
                ),
            )
        )

    try:
        await send("work_reset", "old")
        await send("work_reset", "new")
        await send("output", "old", "迟到")
        await send("work_reset", "old")
        await send("output", "new", "当前")
        assert [(event.action, event.invocation_id) for event in shown] == [
            ("work_reset", "old"),
            ("work_reset", "new"),
            ("output", "new"),
        ]
    finally:
        module.close()


@pytest.mark.asyncio
async def test_chapter_reset_retires_old_lanes_but_keeps_other_chapters_after_restart(db_session):
    from src.sse.persistence import SseMessageRepository
    from src.storage.db import get_session_factory
    from tests.support.chapter_annotation_helpers import create_run_with_chunks

    _novel, run_id = create_run_with_chunks(db_session, texts=["完成章。", "未完成章。"], chapter_ids=[1, 2])
    task_id = task_for_run(run_id, db_session)
    outbox = SseMessageRepository(storage_factory(get_session_factory()))
    manager = EventManager(outbox=outbox)
    try:
        scenarios = [(1, "complete", "saved", "annotation"), (2, "old-event", "old", "event")]
        for chapter, work, invocation, role in scenarios:
            data = {
                "invocation_id": invocation,
                "chapter_id": chapter,
                "stage": "annotate",
                "sub_stage": role,
            }
            await manager.send(task_id, "work_reset", {**data, "message_id": f"{run_id}:reset:{work}"})
            await manager.send(
                task_id, "llm_output", {**data, "content": work, "message_id": f"{run_id}:output:{work}"}
            )
        await manager.send(task_id, "chapter_reset", {"stage": "annotate", "chapter_id": 2})
        data = {
            "invocation_id": fixture_id(__name__, "new"),
            "chapter_id": 2,
            "stage": "annotate",
            "sub_stage": "annotation",
        }
        await manager.send(task_id, "work_reset", {**data, "message_id": f"{run_id}:reset:annotation"})
        await manager.send(
            task_id, "llm_output", {**data, "content": "new-annotation", "message_id": f"{run_id}:output:annotation"}
        )
        restarted = EventManager(outbox=outbox)
        try:
            await restarted.send(
                task_id,
                "llm_output",
                {
                    "stage": "annotate",
                    "chapter_id": 2,
                    "sub_stage": "event",
                    "invocation_id": fixture_id(__name__, "old"),
                    "content": "迟到旧角色",
                    "message_id": f"{run_id}:late",
                },
            )
            replay = await restarted.replay(task_id, 0)
            assert [message["data"]["content"] for message in replay if message["type"] == "llm_output"] == [
                "complete",
                "new-annotation",
            ]
        finally:
            restarted.reset_for_testing()
    finally:
        manager.reset_for_testing()


def test_outbox_keeps_identity_route_emitted_bytes_and_publication(db_session):
    """验证发件箱宽行保存消息身份、路由、当时发出字节与投递事实，
    并以原字节解码重放（中文契约不变）
    """
    from src.sse.persistence import SseMessageRepository
    from src.storage.db import get_session_factory
    from src.storage.models import EventOutbox
    from src.storage.repositories.event_outbox import decode_document
    from tests.support.chapter_annotation_helpers import create_run_with_chunks

    _novel, run_id = create_run_with_chunks(db_session, texts=["原文。"], chapter_ids=[2])
    task_id = task_for_run(run_id, db_session)
    outbox = SseMessageRepository(storage_factory(get_session_factory()))
    data = {
        "message_id": f"document:{run_id}",
        "invocation_id": fixture_id(__name__, "inv-1"),
        "chapter_id": 2,
        "stage": "annotate",
        "sub_stage": "annotation",
        "content": "中文内容：住手",
    }
    emitted = outbox.emit(task_id, "llm_output", data)

    db_session.rollback()
    from sqlalchemy import select

    row = db_session.scalar(
        select(EventOutbox).where(EventOutbox.run_id == run_id, EventOutbox.message_key == data["message_id"])
    )
    assert (row.run_id, row.chapter_id, row.event_type) == (run_id, 2, "llm_output")
    assert row.created_at is not None
    assert decode_document(bytes(row.emitted_bytes)) == {
        "type": "llm_output",
        "data": data,
        "message_id": data["message_id"],
    }
    assert row.published_at is not None

    replayed = outbox.replay(task_id, 0)
    assert replayed == [{"type": "llm_output", "data": data, "seq": emitted["seq"]}]
    assert isinstance(emitted["seq"], int) and emitted["seq"] > 0


def test_outbox_rejects_same_message_id_with_different_content(db_session):
    """验证同一消息身份的重复投递只要内容不同就报冲突，不改写已发出字节"""
    from src.sse.persistence import SseMessageRepository
    from src.storage.db import get_session_factory
    from tests.support.chapter_annotation_helpers import create_run_with_chunks

    _novel, run_id = create_run_with_chunks(db_session, texts=["原文。"])
    task_id = task_for_run(run_id, db_session)
    outbox = SseMessageRepository(storage_factory(get_session_factory()))
    data = {"message_id": f"conflict:{run_id}", "invocation_id": fixture_id(__name__, "inv-1"), "content": "原始内容"}
    first = outbox.emit(task_id, "llm_output", data)

    with pytest.raises(ValueError, match="冲突"):
        outbox.emit(task_id, "llm_output", {**data, "content": "改写内容"})
    assert outbox.reserve_sequence(task_id, data["message_id"]) == first["seq"]

    replayed = outbox.replay(task_id, 0)
    assert [message["data"]["content"] for message in replayed] == ["原始内容"]
