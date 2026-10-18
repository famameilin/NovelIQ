"""模型池容量账本与选举规则：并发为空且选举不出来必须报错停止"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from src.config import settings
from src.event_bus import EventBus, Message
from src.model_pool.capacity import MODEL_CAPACITY, ModelElectionExhausted, ModelElectionPool
from src.model_pool.contracts import SelectionRequest, SelectionResult
from src.work.annotation_work import WorkReceipt
from src.work.chapter_pool import ChapterWorkerPool


def _receipt(run_id: str = "run", work_id: str = "work") -> WorkReceipt:
    return WorkReceipt(
        work_id,
        run_id,
        "annotation_agent",
        {
            "chapter_id": 1,
            "chapter_sequence": 1,
            "chapter_label": "第1章",
            "chapter_text": "原文。",
            "chapter_chars": 3,
            "role": "annotation",
            "paragraphs": [
                SimpleNamespace(chapter_id=1, paragraph_id=1, local_start_char=0, local_end_char=3, text="原文。")
            ],
        },
    )


def _single_slot_pool(monkeypatch: Any) -> None:
    monkeypatch.setattr(settings.models, "model_pool", [SimpleNamespace(model_id="test", max_in_flight=1, weight=1.0)])


async def _enqueue(bus: EventBus, pool: ModelElectionPool) -> None:
    await bus.request(
        Message(
            topic="pool.enqueue",
            source="queue:run",
            target=pool.address,
            run_id="run",
            work_id="work",
            payload=SelectionRequest("run", "work"),
        )
    )


def test_ledger_counts_and_returns_reservations() -> None:
    """占用数就是账本里的预留条数，归还按归属幂等"""
    MODEL_CAPACITY.reserve("model_pool:a", "r1", "test")
    MODEL_CAPACITY.reserve("model_pool:a", "r2", "test")
    MODEL_CAPACITY.reserve("model_pool:b", "r3", "other")

    assert MODEL_CAPACITY.snapshot() == {"test": 2, "other": 1}

    assert MODEL_CAPACITY.release("model_pool:a", "r1") == 1
    assert MODEL_CAPACITY.release("model_pool:a", "r1") == 0
    assert MODEL_CAPACITY.snapshot() == {"test": 1, "other": 1}

    assert MODEL_CAPACITY.release("model_pool:a") == 1
    assert MODEL_CAPACITY.snapshot() == {"other": 1}


def test_close_returns_every_reservation_booked_under_pool_ownership() -> None:
    """池子退出按归属归还：即使预留没进池子自己的账，也不会留在全局账本上"""
    bus = EventBus()
    pool = ModelElectionPool(bus, "run", max_attempts=1)
    MODEL_CAPACITY.reserve(pool.address, "booked-directly", "test")
    assert any(MODEL_CAPACITY.snapshot().values())

    pool.close()

    assert not any(MODEL_CAPACITY.snapshot().values())


@pytest.mark.asyncio
async def test_live_pool_occupancy_keeps_election_waiting(monkeypatch: Any) -> None:
    """仍有池子在占用容量（并发不为空）时继续等待，容量释放后照常选举派发"""
    _single_slot_pool(monkeypatch)
    bus = EventBus()
    other = ModelElectionPool(bus, "other", max_attempts=1, poll_seconds=0.001)
    MODEL_CAPACITY.reserve(other.address, "busy", "test")
    pool = ModelElectionPool(bus, "run", max_attempts=1, poll_seconds=0.001)
    assignments = bus.subscribe(pool.assignment_topic)
    await _enqueue(bus, pool)

    election = asyncio.create_task(pool.run())
    await asyncio.sleep(0.05)
    assert not election.done()

    MODEL_CAPACITY.release(other.address, "busy")
    message = await asyncio.wait_for(assignments.get(), 2)
    assert message.work_id == "work"
    assert isinstance(message.payload, SelectionResult)
    assert message.payload.model_id == "test"
    assert not hasattr(message.payload, "payload")

    election.cancel()
    await asyncio.gather(election, return_exceptions=True)
    pool.close()
    other.close()


@pytest.mark.asyncio
async def test_empty_slot_and_unavailable_model_stops_analysis(monkeypatch: Any) -> None:
    """并发为空且选举不出来时立即报错停止，不空转"""
    _single_slot_pool(monkeypatch)
    bus = EventBus()
    monkeypatch.setattr("src.model_pool.selection.select_annotation_model", lambda *args, **kwargs: None)
    pool = ModelElectionPool(bus, "run", max_attempts=1, poll_seconds=0.001)
    await _enqueue(bus, pool)

    with pytest.raises(ModelElectionExhausted):
        await asyncio.wait_for(pool.run(), 2)

    pool.close()


def _storage(db_session: Any) -> Any:
    """业务存储入口：执行行由审计在派发时登记，队列只写正式产物"""
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=db_session.get_bind())


@pytest.mark.asyncio
async def test_queue_propagates_election_failure_reason(monkeypatch: Any, db_session: Any) -> None:
    """选举失败的真实原因必须传到调用方，且不落任何正式产物"""
    from src.storage.models import ChapterAnnotation
    from src.utils.identity import stable_uuid
    from src.work.annotation_work import annotation_work_id
    from tests.support.chapter_annotation_helpers import create_run_with_chunks

    monkeypatch.setattr(settings.models, "model_pool", [])
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文。"])
    # 派发单元的稳定票据身份与正式产物 record_id 同一来源
    receipt = _receipt(run_id=run_id, work_id=annotation_work_id(run_id, 1, "annotation"))

    with pytest.raises(ValueError, match="正权重"):
        await asyncio.wait_for(
            ChapterWorkerPool(max_attempts=1, poll_seconds=0.001).run(
                [receipt], bus=EventBus(), session_factory=_storage(db_session)
            ),
            2,
        )

    assert not any(MODEL_CAPACITY.snapshot().values())
    # 没有任何正式产物：模型池结束分析时 work 未保存
    assert db_session.get(ChapterAnnotation, stable_uuid(run_id, receipt.work_id)) is None


@pytest.mark.asyncio
async def test_queue_appends_no_stop_message_when_pool_ends_analysis(
    monkeypatch: Any, db_session: Any
) -> None:
    """模型池直接结束分析时不追加队列停止消息，也没有在飞 work 可停"""
    from tests.support.chapter_annotation_helpers import create_run_with_chunks

    monkeypatch.setattr(settings.models, "model_pool", [])
    bus = EventBus()
    stop_messages: list[Message] = []

    async def spy(message: Message) -> None:
        stop_messages.append(message)

    bus.handle("agent.cancel", "agent:run", spy)

    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文。"])
    with pytest.raises(ValueError, match="正权重"):
        await asyncio.wait_for(
            ChapterWorkerPool(max_attempts=1, poll_seconds=0.001).run(
                [_receipt(run_id=run_id, work_id=f"work-{uuid4().hex[:8]}")],
                bus=bus,
                session_factory=_storage(db_session),
            ),
            2,
        )

    assert stop_messages == []


@pytest.mark.asyncio
async def test_pool_rejects_business_envelope_and_mismatched_identity() -> None:
    bus = EventBus()
    pool = ModelElectionPool(bus, "run", max_attempts=1)
    try:
        with pytest.raises(TypeError, match="SelectionRequest"):
            await pool.enqueue(
                Message(
                    topic="pool.enqueue",
                    source="queue:run",
                    target=pool.address,
                    run_id="run",
                    work_id="work",
                    payload=_receipt(),
                )
            )
        with pytest.raises(ValueError, match="身份"):
            await pool.enqueue(
                Message(
                    topic="pool.enqueue",
                    source="queue:run",
                    target=pool.address,
                    run_id="run",
                    work_id="other",
                    payload=SelectionRequest("run", "work"),
                )
            )
        assert not pool.pending
        assert not MODEL_CAPACITY.snapshot()
    finally:
        pool.close()
