"""模型池容量账本与选举规则：并发为空且选举不出来必须报错停止"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from src.config import settings
from src.event_bus import EventBus, Message
from src.model_pool.capacity import MODEL_CAPACITY, ModelElectionExhausted, ModelElectionPool
from src.model_pool.contracts import SelectionRequest, SelectionResult
from src.model_pool.health import MODEL_HEALTH
from src.storage import new_id
from src.work.annotation_work import WorkReceipt
from src.work.chapter_pool import ChapterWorkerPool
from tests.support.storage_fixtures import fixture_id


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


def _model(model_id: str, *, max_in_flight: int = 1, weight: float = 1.0) -> SimpleNamespace:
    """池内条目：身份与模型名分离，容量与健康分按条目身份记账"""
    return SimpleNamespace(
        model_id=model_id,
        base_url=f"https://{model_id}.example/v1",
        entry_id=f"entry-{model_id}",
        max_in_flight=max_in_flight,
        weight=weight,
    )


def _single_slot_pool(monkeypatch: Any) -> None:
    monkeypatch.setattr(settings.models, "model_pool", [_model("test")])


async def _enqueue(bus: EventBus, pool: ModelElectionPool) -> None:
    await bus.request(
        Message(
            topic="pool.enqueue",
            source="queue:run",
            target=pool.address,
            run_id=fixture_id(__name__, "run"),
            work_id="work",
            payload=SelectionRequest(fixture_id(__name__, "run"), "work"),
        )
    )


def test_ledger_counts_and_returns_reservations() -> None:
    """占用数就是账本里的预留条数，归还按归属幂等"""
    MODEL_CAPACITY.reserve("model_pool:a", "r1", "test", "entry-test")
    MODEL_CAPACITY.reserve("model_pool:a", "r2", "test", "entry-test")
    MODEL_CAPACITY.reserve("model_pool:b", "r3", "other", "entry-other")

    assert MODEL_CAPACITY.snapshot() == {"entry-test": 2, "entry-other": 1}

    assert MODEL_CAPACITY.release("model_pool:a", "r1") == 1
    assert MODEL_CAPACITY.release("model_pool:a", "r1") == 0
    assert MODEL_CAPACITY.snapshot() == {"entry-test": 1, "entry-other": 1}

    assert MODEL_CAPACITY.release("model_pool:a") == 1
    assert MODEL_CAPACITY.snapshot() == {"entry-other": 1}


def test_close_returns_every_reservation_booked_under_pool_ownership() -> None:
    """池子退出按归属归还：即使预留没进池子自己的账，也不会留在全局账本上"""
    bus = EventBus()
    pool = ModelElectionPool(bus, fixture_id(__name__, "run"))
    MODEL_CAPACITY.reserve(pool.address, "booked-directly", "test", "entry-test")
    assert any(MODEL_CAPACITY.snapshot().values())

    pool.close()

    assert not any(MODEL_CAPACITY.snapshot().values())


@pytest.mark.asyncio
async def test_live_pool_occupancy_keeps_election_waiting(monkeypatch: Any) -> None:
    """仍有池子在占用容量（并发不为空）时继续等待，容量释放后照常选举派发"""
    _single_slot_pool(monkeypatch)
    bus = EventBus()
    other = ModelElectionPool(bus, "other", poll_seconds=0.001)
    MODEL_CAPACITY.reserve(other.address, "busy", "test", "entry-test")
    pool = ModelElectionPool(bus, fixture_id(__name__, "run"), poll_seconds=0.001)
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
async def test_pool_skips_model_below_health_threshold(monkeypatch: Any) -> None:
    """健康分低于阈值时该模型不参选，派发落到健康模型"""
    monkeypatch.setattr(
        settings.models,
        "model_pool",
        [
            _model("low"),
            _model("healthy"),
        ],
    )
    MODEL_HEALTH.record_turn("entry-low", success=False)
    bus = EventBus()
    pool = ModelElectionPool(bus, fixture_id(__name__, "run"), poll_seconds=0.001)
    assignments = bus.subscribe(pool.assignment_topic)
    await _enqueue(bus, pool)

    election = asyncio.create_task(pool.run())
    message = await asyncio.wait_for(assignments.get(), 2)
    assert isinstance(message.payload, SelectionResult)
    assert message.payload.model_id == "healthy"

    election.cancel()
    await asyncio.gather(election, return_exceptions=True)
    pool.close()


@pytest.mark.asyncio
async def test_pool_waits_until_health_recovers(monkeypatch: Any) -> None:
    """全部模型低于阈值时等待回升，不报错退出；回升后继续派发"""
    _single_slot_pool(monkeypatch)
    MODEL_HEALTH.record_turn("entry-test", success=False)
    bus = EventBus()
    pool = ModelElectionPool(bus, fixture_id(__name__, "run"), poll_seconds=0.001)
    assignments = bus.subscribe(pool.assignment_topic)
    await _enqueue(bus, pool)

    election = asyncio.create_task(pool.run())
    await asyncio.sleep(0.05)
    assert not election.done()

    MODEL_HEALTH.reset(["entry-test"])
    message = await asyncio.wait_for(assignments.get(), 2)
    assert isinstance(message.payload, SelectionResult)
    assert message.payload.model_id == "test"

    election.cancel()
    await asyncio.gather(election, return_exceptions=True)
    pool.close()


@pytest.mark.asyncio
async def test_single_work_pinned_model_overrides_weighted_election(monkeypatch: Any) -> None:
    """单条工作指定承载模型时按该模型预留容量，不受权重与其它空闲模型影响"""
    monkeypatch.setattr(
        settings.models,
        "model_pool",
        [
            _model("weighted"),
            _model("pinned", weight=0),
        ],
    )
    bus = EventBus()
    pool = ModelElectionPool(bus, fixture_id(__name__, "run"), poll_seconds=0.001)
    assignments = bus.subscribe(pool.assignment_topic)
    await bus.request(
        Message(
            topic="pool.enqueue",
            source="queue:run",
            target=pool.address,
            run_id=fixture_id(__name__, "run"),
            work_id="report",
            payload=SelectionRequest(fixture_id(__name__, "run"), "report", fixed_model_id="pinned"),
        )
    )
    election = asyncio.create_task(pool.run())
    try:
        message = await asyncio.wait_for(assignments.get(), 2)
        assert message.payload.model_id == "pinned"
        assert message.payload.entry_id == "entry-pinned"
        assert MODEL_CAPACITY.snapshot() == {"entry-pinned": 1}
    finally:
        election.cancel()
        await asyncio.gather(election, return_exceptions=True)
        pool.close()


@pytest.mark.asyncio
async def test_simultaneous_requests_fill_every_model_slot(monkeypatch: Any) -> None:
    """四路请求同时选举时按空位铺满两个模型的全部并发位"""
    monkeypatch.setattr(
        settings.models,
        "model_pool",
        [
            _model("m-a", max_in_flight=2),
            _model("m-b", max_in_flight=2),
        ],
    )
    bus = EventBus()
    run_id = fixture_id(__name__, "run")
    pool = ModelElectionPool(bus, run_id, poll_seconds=0.001)
    assignments = bus.subscribe(pool.assignment_topic)
    for index in range(4):
        await bus.request(
            Message(
                topic="pool.enqueue",
                source="queue:run",
                target=pool.address,
                run_id=run_id,
                work_id=f"case:{index}",
                payload=SelectionRequest(run_id, f"case:{index}"),
            )
        )
    election = asyncio.create_task(pool.run())
    try:
        results = [await asyncio.wait_for(assignments.get(), 2) for _ in range(4)]
        assert sorted(item.payload.model_id for item in results) == ["m-a", "m-a", "m-b", "m-b"]
        assert MODEL_CAPACITY.snapshot() == {"entry-m-a": 2, "entry-m-b": 2}
    finally:
        election.cancel()
        await asyncio.gather(election, return_exceptions=True)
        pool.close()


@pytest.mark.asyncio
async def test_empty_slot_and_unavailable_model_stops_analysis(monkeypatch: Any) -> None:
    """并发为空且选举不出来时立即报错停止，不空转"""
    _single_slot_pool(monkeypatch)
    bus = EventBus()
    monkeypatch.setattr("src.model_pool.selection.select_annotation_model", lambda *args, **kwargs: None)
    pool = ModelElectionPool(bus, fixture_id(__name__, "run"), poll_seconds=0.001)
    await _enqueue(bus, pool)

    with pytest.raises(ModelElectionExhausted):
        await asyncio.wait_for(pool.run(), 2)

    pool.close()


async def test_reselection_keeps_identity_and_has_no_attempt_limit(monkeypatch: Any) -> None:
    _single_slot_pool(monkeypatch)
    bus = EventBus()
    pool = ModelElectionPool(bus, fixture_id(__name__, "run"), poll_seconds=0.001)
    assignments = bus.subscribe(pool.assignment_topic)
    await _enqueue(bus, pool)
    task = asyncio.create_task(pool.run())
    try:
        for attempt in range(1, 9):
            selected = (await asyncio.wait_for(assignments.get(), 2)).payload
            assert selected.work_id == "work" and selected.attempt_number == attempt
            feedback = Message("pool.feedback", "queue:run", pool.address, pool.run_id, work_id="work",
                               payload={"reservation_id": selected.reservation_id, "outcome": "retry"})
            await bus.request(feedback)
            await bus.request(feedback)
            pool.available_at["work"] = 0
            await _enqueue(bus, pool)
        assert not task.done()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        pool.close()
    assert not MODEL_CAPACITY.snapshot()


async def test_retry_backoff_remains_bounded_at_large_attempt_numbers(monkeypatch: Any) -> None:
    _single_slot_pool(monkeypatch)
    bus = EventBus()
    pool = ModelElectionPool(bus, fixture_id(__name__, "run"))
    pool.attempts["work"] = 1000000
    pool.reservations["work"] = ("reservation", "entry-test")
    MODEL_CAPACITY.reserve(pool.address, "reservation", "test", "entry-test")
    monkeypatch.setattr("src.model_pool.capacity.time.monotonic", lambda: 100)
    try:
        await pool.feedback(Message("pool.feedback", "queue:run", pool.address, pool.run_id, work_id="work",
                                    payload={"reservation_id": "reservation", "outcome": "retry"}))
        assert 130 <= pool.available_at["work"] <= 131
    finally:
        pool.close()


@pytest.mark.asyncio
async def test_final_non_success_records_health_failure_for_selected_entry(monkeypatch: Any) -> None:
    """最终未成功的尝试按条目记一次健康失败，成功与取消不记"""
    _single_slot_pool(monkeypatch)
    bus = EventBus()
    pool = ModelElectionPool(bus, fixture_id(__name__, "run"))
    pool.attempts["work"] = 1
    try:
        for reservation, success, expected in (
            ("reservation-1", False, 1),
            ("reservation-2", None, 1),
            ("reservation-3", True, 1),
            ("reservation-4", False, 2),
        ):
            pool.reservations["work"] = (reservation, "entry-test")
            MODEL_CAPACITY.reserve(pool.address, reservation, "test", "entry-test")
            await pool.feedback(
                Message(
                    "pool.feedback",
                    "queue:run",
                    pool.address,
                    pool.run_id,
                    work_id="work",
                    payload={"reservation_id": reservation, "outcome": "released", "success": success},
                )
            )
            assert MODEL_HEALTH.stats("entry-test")["failure_total"] == expected
    finally:
        pool.close()


@pytest.mark.asyncio
async def test_same_model_on_two_endpoints_reserves_capacity_separately(monkeypatch: Any) -> None:
    """同一模型挂两个端点时按条目分别占用容量，并发上限为两条之和"""
    monkeypatch.setattr(
        settings.models,
        "model_pool",
        [
            SimpleNamespace(model_id="same", base_url="https://a.example/v1", entry_id="entry-a",
                            max_in_flight=1, weight=1.0),
            SimpleNamespace(model_id="same", base_url="https://b.example/v1", entry_id="entry-b",
                            max_in_flight=1, weight=1.0),
        ],
    )
    bus = EventBus()
    run_id = fixture_id(__name__, "run")
    pool = ModelElectionPool(bus, run_id, poll_seconds=0.001)
    assignments = bus.subscribe(pool.assignment_topic)
    for index in range(3):
        await bus.request(
            Message(
                topic="pool.enqueue",
                source="queue:run",
                target=pool.address,
                run_id=run_id,
                work_id=f"work:{index}",
                payload=SelectionRequest(run_id, f"work:{index}"),
            )
        )
    election = asyncio.create_task(pool.run())
    try:
        results = [await asyncio.wait_for(assignments.get(), 2) for _ in range(2)]
        assert sorted(item.payload.entry_id for item in results) == ["entry-a", "entry-b"]
        assert {item.payload.model_id for item in results} == {"same"}
        assert MODEL_CAPACITY.snapshot() == {"entry-a": 1, "entry-b": 1}
        await asyncio.sleep(0.05)
        assert not election.done()
    finally:
        election.cancel()
        await asyncio.gather(election, return_exceptions=True)
        pool.close()


def _storage(db_session: Any) -> Any:
    """业务存储入口：执行行由审计在派发时登记，队列只写正式产物"""
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=db_session.get_bind())


@pytest.mark.asyncio
async def test_queue_propagates_election_failure_reason(monkeypatch: Any, db_session: Any) -> None:
    """选举失败的真实原因必须传到调用方，且不落任何正式产物"""
    from src.storage.models import ChapterAnnotation
    from src.work.annotation_work import annotation_work_id
    from tests.support.chapter_annotation_helpers import create_run_with_chunks
    from tests.support.storage_fixtures import fixture_id

    monkeypatch.setattr(settings.models, "model_pool", [])
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["原文。"])
    # 派发单元的稳定票据身份与正式产物 record_id 同一来源
    receipt = _receipt(run_id=run_id, work_id=annotation_work_id(run_id, 1, "annotation"))

    with pytest.raises(ValueError, match="正权重"):
        await asyncio.wait_for(
            ChapterWorkerPool(poll_seconds=0.001).run(
                [receipt], bus=EventBus(), session_factory=_storage(db_session)
            ),
            2,
        )

    assert not any(MODEL_CAPACITY.snapshot().values())
    # 没有任何正式产物：模型池结束分析时 work 未保存
    assert db_session.get(ChapterAnnotation, fixture_id(run_id, receipt.work_id)) is None


@pytest.mark.asyncio
async def test_queue_appends_no_stop_message_when_pool_ends_analysis(monkeypatch: Any, db_session: Any) -> None:
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
            ChapterWorkerPool(poll_seconds=0.001).run(
                [_receipt(run_id=run_id, work_id=f"work-{new_id()}")],
                bus=bus,
                session_factory=_storage(db_session),
            ),
            2,
        )

    assert stop_messages == []


@pytest.mark.asyncio
async def test_pool_rejects_business_envelope_and_mismatched_identity() -> None:
    bus = EventBus()
    pool = ModelElectionPool(bus, fixture_id(__name__, "run"))
    try:
        with pytest.raises(TypeError, match="SelectionRequest"):
            await pool.enqueue(
                Message(
                    topic="pool.enqueue",
                    source="queue:run",
                    target=pool.address,
                    run_id=fixture_id(__name__, "run"),
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
                    run_id=fixture_id(__name__, "run"),
                    work_id="other",
                    payload=SelectionRequest(fixture_id(__name__, "run"), "work"),
                )
            )
        assert not pool.pending
        assert not MODEL_CAPACITY.snapshot()
    finally:
        pool.close()
