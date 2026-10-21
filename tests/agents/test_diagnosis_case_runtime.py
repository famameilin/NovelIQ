"案例会话调度、事务取消与批量读取"

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.agents.annotation.shared_tools import build_finish_tool, build_state_read_tools
from src.agents.diagnosis.read_context import DiagnosisAnnotationEventSource
from src.agents.diagnosis.work_runtime import DiagnosisWorkContext, DiagnosisWorkScheduler
from src.event_bus import EventBus
from src.event_trees.organization import EventOrganizationDraft
from src.model_pool.contracts import SelectionResult
from src.storage import new_id


def scheduler_for(domain):
    return DiagnosisWorkScheduler(
        run_id=new_id(), domain=domain, bus=EventBus(), model_id="test",
        llm_factory=Mock(), observer_factory=Mock(), audit_barrier=AsyncMock(), case_sessions=3,
    )


async def test_single_pending_case_starts_one_session(monkeypatch):
    counts = [1, 0]
    domain = SimpleNamespace(case_counts=lambda: tuple(counts), analysis_result=lambda: "report")
    scheduler = scheduler_for(domain)
    started = []

    async def session(key, role):
        started.append((key, role))
        counts[:] = [0, 1]

    monkeypatch.setattr(scheduler, "_session", session)
    monkeypatch.setattr(scheduler, "_wave", AsyncMock())
    assert await scheduler._run_work() == "report"
    assert len(started) == 1


def session_scheduler(monkeypatch, *, state=None, pending_after_capacity=1, claimed=0, unsubmitted=0, save=None):
    program = SimpleNamespace(build_tool=lambda: object(), tools={"finish": build_finish_tool(lambda: {})})
    context = DiagnosisWorkContext(program, [], lambda: [], 15, lambda: claimed, lambda: unsubmitted)
    domain = SimpleNamespace(
        case_counts=lambda: (pending_after_capacity, 0),
        build_session_context=Mock(return_value=context),
        save_session_progress=save or Mock(), abort_session=Mock(),
    )
    scheduler = scheduler_for(domain)
    recorder = Mock(sequence=0)
    observer = SimpleNamespace(_recorder=recorder, _context={"agent_id": "a"}, _turn_counter=0)
    scheduler.observer_factory.return_value = observer
    graph = SimpleNamespace(ainvoke=AsyncMock(return_value=state or {"iterations": 1}))
    monkeypatch.setattr("src.agents.annotation.agent_graph.build_agent_graph", lambda *a, **k: graph)

    async def request(message):
        if message.topic == "pool.enqueue":
            scheduler._waiting[message.work_id].set_result(
                SelectionResult(scheduler.run_id, message.work_id, "test", 1, "reservation")
            )

    monkeypatch.setattr(scheduler.bus, "request", AsyncMock(side_effect=request))
    return scheduler, domain, recorder


async def test_capacity_wait_ending_with_empty_pool_skips_model(monkeypatch):
    scheduler, domain, recorder = session_scheduler(monkeypatch, pending_after_capacity=0)
    await scheduler._session("case:1", "case")
    scheduler.llm_factory.assert_not_called()
    domain.build_session_context.assert_not_called()
    recorder.finish_invocation.assert_not_called()
    assert scheduler.bus.request.call_args.args[0].topic == "pool.feedback"


async def test_exhausted_session_without_claim_fails_and_releases_capacity(monkeypatch):
    scheduler, domain, recorder = session_scheduler(monkeypatch, state={"iterations": 15, "halted": True})
    with pytest.raises(RuntimeError, match="没有新增领取"):
        await scheduler._session("case:1", "case")
    domain.save_session_progress.assert_not_called()
    domain.abort_session.assert_called_once()
    assert recorder.finish_invocation.call_args.kwargs["status"] == "error"
    assert scheduler.bus.request.call_args.args[0].topic == "pool.feedback"


async def test_exhausted_session_with_claim_saves_progress(monkeypatch):
    scheduler, domain, recorder = session_scheduler(
        monkeypatch, state={"iterations": 15, "halted": True}, claimed=1,
    )
    await scheduler._session("case:1", "case")
    domain.save_session_progress.assert_called_once()
    assert recorder.finish_invocation.call_args.kwargs["status"] == "success"


async def test_exhausted_unsubmitted_claim_saves_valid_outputs_and_stops_round(monkeypatch):
    scheduler, domain, recorder = session_scheduler(
        monkeypatch, state={"iterations": 15, "halted": True}, claimed=1, unsubmitted=1,
    )
    with pytest.raises(RuntimeError, match="未提交领取"):
        await scheduler._session("case:1", "case")
    domain.save_session_progress.assert_called_once()
    domain.abort_session.assert_not_called()
    assert recorder.finish_invocation.call_args.kwargs["status"] == "error"
    assert scheduler.bus.request.call_args.args[0].topic == "pool.feedback"


async def test_repeated_cancellation_waits_for_save_and_confirms_success(monkeypatch):
    started, release, committed = threading.Event(), threading.Event(), threading.Event()

    def save(*_):
        started.set()
        assert release.wait(2)
        committed.set()

    scheduler, domain, recorder = session_scheduler(monkeypatch, claimed=1, save=save)
    task = asyncio.create_task(scheduler._session("case:1", "case"))
    assert await asyncio.to_thread(started.wait, 2)
    try:
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert committed.is_set()
    domain.abort_session.assert_not_called()
    assert recorder.finish_invocation.call_args.kwargs["status"] == "success"
    assert "save_ms" in recorder.finish_invocation.call_args.kwargs["runtime_timings"]


def test_search_page_builds_book_once_and_batches_positions():
    rows = {
        str(i): SimpleNamespace(
            title=str(i), problem="problem", summary="summary", event_type="plot", status="ongoing",
            progress="step", from_chapter_id=1, to_chapter_id=1, is_foreshadowing_root=False,
        ) for i in range(10)
    }
    reads = SimpleNamespace(
        event_trees_organization_annotation_event_rows_1=lambda _: [],
        event_trees_organization_parents_1=lambda _: [],
    )
    draft = EventOrganizationDraft(SimpleNamespace(reads=reads), "run")
    source = DiagnosisAnnotationEventSource(draft)
    tools = build_state_read_tools(
        object(), source, event_reads={}, entity_ids=set(), case_reads=[], resolve_event=lambda key: key,
    )
    search = next(tool for tool in tools if tool.name == "search_events")
    evidence = [[{"paragraph_id": i, "char_start": 0}] for i in range(10)]
    with (
        patch("src.event_trees.organization.smap.run_events", return_value=rows) as load,
        patch("src.event_trees.organization.smap.fetch_evidence", return_value={}),
        patch("src.event_trees.organization.smap.evidence_payload_groups", return_value=evidence),
        patch("src.event_trees.organization._global_positions", return_value=dict.fromkeys(range(10), 0)) as positions,
    ):
        search.invoke({"query": "", "limit": 10})
    load.assert_called_once()
    positions.assert_called_once()
    assert positions.call_args.args[2] == set(range(10))
