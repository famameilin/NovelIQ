"""模型池容量账本与选举规则：并发为空且选举不出来必须报错停止"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from src.config import settings
from src.event_bus import EventBus, Message
from src.model_pool.capacity import MODEL_CAPACITY, ModelElectionExhausted, ModelElectionPool
from src.work.annotation_work import WorkReceipt
from src.workflows.chapter_pool import ChapterWorkerPool


def _receipt() -> WorkReceipt:
    return WorkReceipt(
        "work",
        "run",
        "annotation_agent",
        {
            "chapter_id": 1,
            "chapter_sequence": 1,
            "chapter_label": "第1章",
            "chapter_text": "原文。",
            "chapter_chars": 3,
            "role": "solo",
            "paragraphs": [
                SimpleNamespace(chapter_id=1, paragraph_id=1, local_start_char=0, local_end_char=3, text="原文。")
            ],
        },
    )


def _single_slot_pool(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        settings.models, "model_pool", [SimpleNamespace(model_id="test", max_in_flight=1, weight=1.0)]
    )


async def _enqueue(bus: EventBus, pool: ModelElectionPool) -> None:
    await bus.request(
        Message(
            topic="pool.enqueue",
            source="queue:run",
            target=pool.address,
            run_id="run",
            work_id="work",
            payload=_receipt(),
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
    assert message.payload.payload["model_id"] == "test"

    election.cancel()
    await asyncio.gather(election, return_exceptions=True)
    pool.close()
    other.close()


@pytest.mark.asyncio
async def test_empty_slot_and_unavailable_model_stops_analysis(monkeypatch: Any) -> None:
    """并发为空且选举不出来时立即报错停止，不空转"""
    _single_slot_pool(monkeypatch)
    bus = EventBus()
    monkeypatch.setattr("src.config.model_assignment.select_annotation_model", lambda *args, **kwargs: None)
    pool = ModelElectionPool(bus, "run", max_attempts=1, poll_seconds=0.001)
    await _enqueue(bus, pool)

    with pytest.raises(ModelElectionExhausted):
        await asyncio.wait_for(pool.run(), 2)

    pool.close()


def _no_storage() -> Any:
    raise AssertionError("模型池结束分析时不得访问业务存储")


@pytest.mark.asyncio
async def test_queue_propagates_election_failure_reason(monkeypatch: Any) -> None:
    """选举失败的真实原因必须传到调用方，且不触碰业务存储"""
    monkeypatch.setattr(settings.models, "model_pool", [])

    with pytest.raises(ValueError, match="正权重"):
        await asyncio.wait_for(
            ChapterWorkerPool(max_attempts=1, poll_seconds=0.001).run(
                [_receipt()], bus=EventBus(), session_factory=_no_storage
            ),
            2,
        )

    assert not any(MODEL_CAPACITY.snapshot().values())


@pytest.mark.asyncio
async def test_queue_appends_no_stop_message_when_pool_ends_analysis(monkeypatch: Any) -> None:
    """模型池直接结束分析时不追加队列停止消息，也没有在飞 work 可停"""
    monkeypatch.setattr(settings.models, "model_pool", [])
    bus = EventBus()
    stop_messages: list[Message] = []

    async def spy(message: Message) -> None:
        stop_messages.append(message)

    bus.handle("agent.cancel", "agent:run", spy)

    with pytest.raises(ValueError, match="正权重"):
        await asyncio.wait_for(
            ChapterWorkerPool(max_attempts=1, poll_seconds=0.001).run(
                [_receipt()], bus=bus, session_factory=_no_storage
            ),
            2,
        )

    assert stop_messages == []
