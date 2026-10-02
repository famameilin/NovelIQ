"""并行工作租约、幂等与取消栅栏"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from src.storage.db import get_session_factory
from src.storage.models import AgentWorkItem, AnalysisRun, EventOutbox, Novel
from src.storage.repositories.pipeline_work import (
    ImmutableWorkConflict,
    PipelineWorkRepository,
    StaleWorkLeaseError,
)

pytestmark = pytest.mark.usefixtures("pipeline_run_cleanup")


def _queue() -> tuple[str, PipelineWorkRepository]:
    run_id = str(uuid4())
    novel_id = uuid4().hex[:8]
    factory = get_session_factory()
    with factory() as session, session.begin():
        session.add(Novel(novel_id=novel_id, title="并行队列测试"))
        session.flush()
        session.add(AnalysisRun(run_id=run_id, novel_id=novel_id, status="running"))
    return run_id, PipelineWorkRepository(factory)


def test_work_queue_claims_distinct_items_and_rejects_changed_input() -> None:
    run_id, queue = _queue()
    first_id = queue.enqueue(
        run_id=run_id, work_kind="formal_current", logical_key="chapter:1",
        payload={"chapter_id": 1}, cutoff_hash="source-1",
    )
    assert first_id == queue.enqueue(
        run_id=run_id, work_kind="formal_current", logical_key="chapter:1",
        payload={"chapter_id": 1}, cutoff_hash="source-1",
    )
    with pytest.raises(ImmutableWorkConflict):
        queue.enqueue(
            run_id=run_id, work_kind="formal_current", logical_key="chapter:1",
            payload={"chapter_id": 1, "changed": True}, cutoff_hash="source-1",
        )
    second_id = queue.enqueue(
        run_id=run_id, work_kind="formal_current", logical_key="chapter:2",
        payload={"chapter_id": 2}, cutoff_hash="source-1",
    )

    first = queue.claim(owner="worker-1")
    second = queue.claim(owner="worker-2")
    assert first is not None and second is not None
    assert {first.work_id, second.work_id} == {first_id, second_id}
    assert queue.claim(owner="worker-3") is None

    with get_session_factory()() as session, session.begin():
        queue.mark_submitted(session, first)
    with pytest.raises(StaleWorkLeaseError):
        queue.heartbeat(first)
    with get_session_factory()() as session:
        assert session.get(AgentWorkItem, first.work_id).state == "submitted"
        event_count = session.execute(
            select(func.count()).select_from(EventOutbox).where(EventOutbox.run_id == run_id)
        ).scalar_one()
        assert event_count == 5


def test_claim_uses_current_pool_and_retry_reselects_model(monkeypatch) -> None:
    from src.config import settings
    from src.config.schemas.model import WeightedModelSettings

    run_id, queue = _queue()
    first_id = queue.enqueue(run_id=run_id, work_kind="formal_current", logical_key="chapter:1",
                             payload={"chapter_id": 1}, cutoff_hash="source")
    monkeypatch.setattr(settings.models, "model_pool", [
        WeightedModelSettings("new-model", "https://new.example/v1", "new-key"),
    ])
    assert queue.enqueue(run_id=run_id, work_kind="formal_current", logical_key="chapter:1",
                         payload={"chapter_id": 1}, cutoff_hash="source") == first_id
    receipt = queue.claim(owner="worker-current-model", run_id=run_id)
    assert receipt is not None and receipt.payload["model_id"] == "new-model"
    monkeypatch.setattr(settings.models, "model_pool", [
        WeightedModelSettings("new-model", "https://new.example/v1", "new-key"),
        WeightedModelSettings("other-model", "https://other.example/v1", "other-key"),
    ])
    queue.fail(receipt, reason="章节失败", transient=True, max_attempts=3, retry_delay_seconds=0)
    retry = queue.claim(owner="worker-retry", run_id=run_id)
    assert retry is not None and retry.attempt_epoch == 2 and retry.payload["model_id"] == "other-model"


def test_expired_work_is_reclaimed_and_old_attempt_is_fenced() -> None:
    run_id, queue = _queue()
    queue.enqueue(
        run_id=run_id, work_kind="formal_current", logical_key="chapter:1",
        payload={"chapter_id": 1}, cutoff_hash="source-1",
    )
    first = queue.claim(owner="worker-1")
    assert first is not None
    with get_session_factory()() as session, session.begin():
        row = session.get(AgentWorkItem, first.work_id)
        row.lease_expires_at = first.lease_expires_at - timedelta(hours=1)

    second = queue.claim(owner="worker-2")
    assert second is not None
    assert second.work_id == first.work_id
    assert second.attempt_epoch == first.attempt_epoch + 1
    with pytest.raises(StaleWorkLeaseError):
        queue.heartbeat(first)
    queue.heartbeat(second)


def test_cancel_epoch_fences_running_work() -> None:
    run_id, queue = _queue()
    queue.enqueue(
        run_id=run_id, work_kind="formal_current", logical_key="chapter:1",
        payload={"chapter_id": 1}, cutoff_hash="source-1",
    )
    receipt = queue.claim(owner="worker-1")
    assert receipt is not None
    assert queue.cancel_run(run_id) == 1
    with pytest.raises(StaleWorkLeaseError):
        with get_session_factory()() as session, session.begin():
            queue.mark_submitted(session, receipt)
    assert queue.claim(owner="worker-2") is None


def test_chapter_claims_have_no_global_task_limit_and_ignore_other_run_queue() -> None:
    orphan_run, queue = _queue()
    active_run, _ = _queue()
    for run_id in (orphan_run, active_run):
        for chapter_id in (1, 2):
            queue.enqueue(run_id=run_id, work_kind="formal_current", logical_key=f"chapter:{chapter_id}",
                          payload={"chapter_id": chapter_id}, cutoff_hash="source")
    first = queue.claim(owner="live-1", run_id=active_run)
    assert first is not None
    second = queue.claim(owner="live-2", run_id=active_run)
    assert second is not None and second.run_id == active_run
    assert second.work_id != first.work_id


def test_large_and_small_run_claims_do_not_share_fixed_chapter_slots() -> None:
    large, queue = _queue()
    small, _ = _queue()
    for run_id, chapters in ((large, range(4)), (small, range(1))):
        for chapter_id in chapters:
            queue.enqueue(run_id=run_id, work_kind="formal_current", logical_key=f"chapter:{chapter_id}",
                          payload={"chapter_id": chapter_id}, cutoff_hash="source")
    first = queue.claim(owner="large-1", run_id=large)
    second = queue.claim(owner="large-2", run_id=large)
    assert first and second
    assert queue.claim(owner="large-3", run_id=large) is not None
    small_receipt = queue.claim(owner="small-1", run_id=small)
    assert small_receipt is not None and small_receipt.run_id == small


def test_expired_attempt_budget_becomes_dead_letter_without_model_retry() -> None:
    run_id, queue = _queue()
    queue.enqueue(run_id=run_id, work_kind="formal_current", logical_key="chapter:1",
                  payload={"chapter_id": 1}, cutoff_hash="source")
    first = queue.claim(owner="worker-1", run_id=run_id, max_attempts=1)
    assert first is not None
    with get_session_factory()() as session, session.begin():
        session.get(AgentWorkItem, first.work_id).lease_expires_at -= timedelta(hours=1)
    assert queue.claim(owner="worker-2", run_id=run_id, max_attempts=1) is None
    assert queue.state_counts(run_id) == {"dead_letter": 1}
