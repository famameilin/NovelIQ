"""持久事件重放与迟到模型审计不能覆盖业务状态"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.agents.audit.recorder import AgentAuditRecorder
from src.api.services.event_manager import EventManager
from src.storage.db import get_session_factory
from src.storage.models import AgentInvocation, EventOutbox
from src.storage.repositories.event_outbox import EventOutboxRepository
from src.storage.repositories.pipeline_work import append_outbox
from tests.support.chapter_annotation_helpers import create_run_with_chunks

pytestmark = pytest.mark.usefixtures("pipeline_run_cleanup")


def test_committed_outbox_replays_after_dispatcher_restart_without_duplicates(db_session) -> None:
    _, run_id = create_run_with_chunks(db_session, texts=["原文"])
    factory = get_session_factory()
    with factory() as session, session.begin():
        first = append_outbox(session, run_id=run_id, event_type="cutoff_sealed", payload={"round_number": 0})
        assert append_outbox(session, run_id=run_id, event_type="cutoff_sealed", payload={"round_number": 0}) == first
    before_restart = EventOutboxRepository(factory).replay(run_id, 0)
    assert len(before_restart) == 1
    cursor = before_restart[0]["seq"]
    repository = EventOutboxRepository(factory)
    repository.emit(run_id, "stage_progress", {"current": 1})
    after_restart = EventOutboxRepository(factory).replay(run_id, cursor)
    assert len(after_restart) == 1 and after_restart[0]["seq"] > cursor
    assert after_restart[0]["type"] == "stage_progress"
    assert after_restart[0]["data"] == {"current": 1}
    with factory() as session:
        assert len(list(session.execute(select(EventOutbox).where(EventOutbox.run_id == run_id)).scalars())) == 2


@pytest.mark.asyncio
async def test_slow_sse_client_has_bounded_memory_and_can_replay_all_events(db_session) -> None:
    _, run_id = create_run_with_chunks(db_session, texts=["原文"])
    repository = EventOutboxRepository(get_session_factory())
    manager = EventManager(buffer_size=2, outbox=repository)
    queue = await manager.connect(run_id)
    try:
        for current in range(6):
            await manager.send(run_id, "stage_progress", {"current": current})
        assert queue.qsize() <= 2
        messages = [await queue.get() for _ in range(queue.qsize())]
        assert any(message["type"] == "reconnect_required" for message in messages)
        replay = EventOutboxRepository(get_session_factory()).replay(run_id, 0)
        assert [item["data"]["current"] for item in replay] == list(range(6))
    finally:
        await manager.disconnect_all(run_id)
        if manager._cleanup_task is not None:
            manager._cleanup_task.cancel()


def test_close_orphaned_invocations_only_sweeps_stale_running_rows(db_session) -> None:
    """2026-10-03 进程重启遗留的 running 审计行收口为 interrupted，已收口行不受影响

    run 08f9ba42 实证 12 条僵尸 running 行污染错误率统计；收口只补状态不删除。
    """
    _, run_id = create_run_with_chunks(db_session, texts=["原文"])
    recorder = AgentAuditRecorder(get_session_factory())
    orphan = recorder.start_invocation(
        run_id=run_id, task_type="annotation", attempt_number=1, model_name="fake", model_provider="test", chapter_id=1
    )
    finished = recorder.start_invocation(
        run_id=run_id, task_type="annotation", attempt_number=1, model_name="fake", model_provider="test", chapter_id=1
    )
    recorder.finish_invocation(finished, status="success")

    assert recorder.close_orphaned_invocations(run_id) == 1
    assert recorder.close_orphaned_invocations(run_id) == 0  # 幂等：二次清扫无事可做

    with get_session_factory()() as session:
        orphaned = session.get(AgentInvocation, orphan)
        assert orphaned.status == "interrupted"
        assert orphaned.finished_at is not None
        assert orphaned.final_error is not None
        done = session.get(AgentInvocation, finished)
        assert done.status == "success"  # 正常收口行不被误扫
