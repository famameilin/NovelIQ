"案例会话调度、事务取消与批量读取"

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.agents.annotation.shared_tools import build_finish_tool, build_state_read_tools
from src.agents.diagnosis.read_context import DiagnosisAnnotationEventSource
from src.agents.diagnosis.work_runtime import DiagnosisWorkContext, DiagnosisWorkScheduler
from src.agents.stream import ModelRequestError
from src.case_pool import CasePool
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


def session_scheduler(
    monkeypatch, *, state=None, pending_after_capacity=1, claimed=0, unsubmitted=0, save=None, model="test",
):
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
                SelectionResult(scheduler.run_id, message.work_id, model, 1, "reservation")
            )

    monkeypatch.setattr(scheduler.bus, "request", AsyncMock(side_effect=request))
    return scheduler, domain, recorder


async def test_session_runs_on_elected_model_and_reports_it_to_observer(monkeypatch):
    scheduler, domain, recorder = session_scheduler(monkeypatch, model="pool-model-b")
    seen: dict[str, str] = {}

    def llm_factory(model: str) -> None:
        seen["llm"] = model

    scheduler.llm_factory = Mock(side_effect=llm_factory)
    base_observer_factory = scheduler.observer_factory

    def observer_factory(progress):
        seen["observer"] = progress.model_id
        return base_observer_factory(progress)

    scheduler.observer_factory = Mock(side_effect=observer_factory)
    await scheduler._session("case:1", "case")
    # 会话按模型池选举结果建模型、登记审计，不依赖固定的诊断模型
    assert seen == {"llm": "pool-model-b", "observer": "pool-model-b"}
    domain.save_session_progress.assert_called_once()
    assert recorder.finish_invocation.call_args.kwargs["status"] == "success"


async def test_case_session_elects_while_report_session_pins_diagnosis_model(monkeypatch):
    scheduler, domain, _ = session_scheduler(monkeypatch)
    scheduler.model_id = "pinned-model"
    await scheduler._session("case:1", "case")
    await scheduler._session(scheduler.report_key, "report")
    enqueues = [
        call.args[0] for call in scheduler.bus.request.call_args_list if call.args[0].topic == "pool.enqueue"
    ]
    # 案例会话按池选举承载模型，报告会话沿用指定诊断模型
    assert [message.payload.fixed_model_id for message in enqueues] == [None, "pinned-model"]


async def test_capacity_wait_ending_with_empty_pool_skips_model(monkeypatch):
    scheduler, domain, recorder = session_scheduler(monkeypatch, pending_after_capacity=0)
    await scheduler._session("case:1", "case")
    scheduler.llm_factory.assert_not_called()
    domain.build_session_context.assert_not_called()
    recorder.finish_invocation.assert_not_called()
    assert scheduler.bus.request.call_args.args[0].topic == "pool.feedback"


@pytest.mark.parametrize("role", ["case", "report"])
@pytest.mark.parametrize("failure", ["budget", "model"])
async def test_failed_session_reselects_same_work_with_fresh_execution(monkeypatch, role, failure):
    scheduler, domain, _ = session_scheduler(monkeypatch)
    responses = [
        {"iterations": 15, "halted": True} if failure == "budget" else ModelRequestError("鉴权失败"),
        {"iterations": 1, "completion_ok": True},
    ]
    graph = SimpleNamespace(ainvoke=AsyncMock(side_effect=responses))
    monkeypatch.setattr("src.agents.annotation.agent_graph.build_agent_graph", lambda *a, **k: graph)
    scheduler.observer_factory.side_effect = lambda progress: SimpleNamespace(
        _recorder=Mock(sequence=0), _context={"agent_id": progress.agent_id}, _turn_counter=0,
    )
    await scheduler._session("stable-work", role)
    messages = [call.args[0] for call in scheduler.bus.request.call_args_list]
    assert [message.work_id for message in messages if message.topic == "pool.enqueue"] == ["stable-work"] * 2
    assert [message.payload["outcome"] for message in messages if message.topic == "pool.feedback"] == [
        "retry", "released",
    ]
    identities = [call.args[0].agent_id for call in scheduler.observer_factory.call_args_list]
    assert len(set(identities)) == 2
    domain.save_session_progress.assert_called_once_with(identities[1], role)
    domain.abort_session.assert_called_once_with(identities[0])


@pytest.mark.parametrize("error", [RuntimeError("项目异常"), TimeoutError("数据库超时")])
async def test_project_exception_is_not_reclassified_as_model_retry(monkeypatch, error):
    scheduler, domain, _ = session_scheduler(monkeypatch)
    graph = SimpleNamespace(ainvoke=AsyncMock(side_effect=error))
    monkeypatch.setattr("src.agents.annotation.agent_graph.build_agent_graph", lambda *a, **k: graph)
    with pytest.raises(type(error), match=str(error)):
        await scheduler._session("case:1", "case")
    assert scheduler.observer_factory.call_count == 1
    domain.save_session_progress.assert_not_called()
    assert scheduler.bus.request.call_args.args[0].payload["outcome"] == "released"


async def test_exhausted_session_without_claim_retries_and_releases_capacity(monkeypatch):
    scheduler, domain, recorder = session_scheduler(monkeypatch, state={"iterations": 15, "halted": True})
    assert await scheduler._attempt("case:1", "case") is True
    domain.save_session_progress.assert_not_called()
    domain.abort_session.assert_called_once()
    assert recorder.finish_invocation.call_args.kwargs["status"] == "error"
    assert scheduler.bus.request.call_args.args[0].topic == "pool.feedback"


async def test_exhausted_session_with_claim_saves_progress(monkeypatch):
    scheduler, domain, recorder = session_scheduler(
        monkeypatch, state={"iterations": 15, "halted": True}, claimed=1,
    )
    await scheduler._attempt("case:1", "case")
    domain.save_session_progress.assert_called_once()
    assert recorder.finish_invocation.call_args.kwargs["status"] == "error"


async def test_exhausted_unsubmitted_claim_saves_valid_outputs_and_returns_for_refill(monkeypatch):
    scheduler, domain, recorder = session_scheduler(
        monkeypatch, state={"iterations": 15, "halted": True}, claimed=1, unsubmitted=1,
    )
    await scheduler._attempt("case:1", "case")
    domain.save_session_progress.assert_called_once()
    domain.abort_session.assert_not_called()
    assert recorder.finish_invocation.call_args.kwargs["status"] == "error"
    assert "回合已耗尽" in recorder.finish_invocation.call_args.kwargs["final_error"]
    recorder.finish_invocation.assert_called_once()
    assert scheduler.bus.request.call_args.args[0].topic == "pool.feedback"


async def test_incomplete_session_without_exhausted_budget_still_reports_failure(monkeypatch):
    scheduler, domain, recorder = session_scheduler(monkeypatch, claimed=1, unsubmitted=1)
    with pytest.raises(RuntimeError, match="未提交领取"):
        await scheduler._attempt("case:1", "case")
    domain.save_session_progress.assert_not_called()
    assert recorder.finish_invocation.call_args.kwargs["status"] == "error"


async def test_exhausted_unsubmitted_claim_does_not_hide_save_failure(monkeypatch):
    scheduler, domain, recorder = session_scheduler(
        monkeypatch, state={"iterations": 15, "halted": True}, claimed=1, unsubmitted=1,
        save=Mock(side_effect=OSError("保存失败")),
    )
    with pytest.raises(OSError, match="保存失败"):
        await scheduler._attempt("case:1", "case")
    domain.abort_session.assert_called_once()
    assert recorder.finish_invocation.call_args.kwargs["status"] == "error"
    assert scheduler.bus.request.call_args.args[0].topic == "pool.feedback"


async def test_exhausted_session_refills_released_case_without_cancelling_other_session(monkeypatch):
    pool = CasePool(new_id())
    pool.begin("producer")
    for index in range(2):
        pool.push("event", f"核查事件{index}", "producer")
    started = []
    saved = {}
    observers = {}
    claims = {}
    slow_started, replacement_started = asyncio.Event(), asyncio.Event()

    def context(role, author, observer):
        pool.begin(author)
        started.append(author)
        program = SimpleNamespace(build_tool=lambda: object(), tools={"finish": build_finish_tool(lambda: {})})
        return DiagnosisWorkContext(
            program, [], lambda: [], 15,
            lambda: len(pool.claims_for(author)), lambda: len(pool.unsubmitted_for(author)),
        )

    def save(author, role):
        saved[author] = pool.contribution(author)
        pool.confirm(author)

    domain = SimpleNamespace(
        case_pool=pool, case_counts=pool.counts, build_session_context=context, save_session_progress=save,
        abort_session=Mock(), analysis_result=lambda: "report",
    )
    scheduler = scheduler_for(domain)

    def observer(progress):
        value = SimpleNamespace(
            _recorder=Mock(sequence=0), _context={"agent_id": progress.agent_id}, _turn_counter=0,
        )
        observers[progress.agent_id] = value
        return value

    scheduler.observer_factory = observer

    async def request(message):
        if message.topic == "pool.enqueue":
            scheduler._waiting[message.work_id].set_result(SelectionResult(
                scheduler.run_id, message.work_id, "test", 1, new_id(),
            ))

    monkeypatch.setattr(scheduler.bus, "request", AsyncMock(side_effect=request))

    def graph(*args, **kwargs):
        author = kwargs["observer"]._context["agent_id"]
        index = len(started)

        async def invoke(*args, **kwargs):
            case = pool.claim_random(author)
            assert case["status"] == "claimed"
            claims[author] = case["case_id"]
            if index == 1:
                await slow_started.wait()
                return {"iterations": 15, "halted": True}
            if index == 2:
                slow_started.set()
                await replacement_started.wait()
            else:
                assert claims[author] == claims[started[0]]
                replacement_started.set()
            pool.submit(case["case_id"], author)
            return {"iterations": 1, "completion_ok": True}

        return SimpleNamespace(ainvoke=invoke)

    monkeypatch.setattr("src.agents.annotation.agent_graph.build_agent_graph", graph)

    async def report(sessions):
        assert sessions == [(scheduler.report_key, "report")]
        assert len(saved) == len(started) == 3
        assert pool.counts() == (0, 2) and pool.unsubmitted_for() == []

    monkeypatch.setattr(scheduler, "_wave", AsyncMock(side_effect=report))
    assert await asyncio.wait_for(scheduler._run_work(), timeout=3) == "report"
    assert saved[started[0]]["submissions"] == []
    for index, author in enumerate(started):
        recorder = observers[author]._recorder
        recorder.finish_invocation.assert_called_once()
        assert recorder.finish_invocation.call_args.kwargs["status"] == ("error" if index == 0 else "success")
    assert len({claims[author] for author in started}) == 2
    domain.abort_session.assert_not_called()
    scheduler._wave.assert_awaited_once()
    feedback = [call.args[0] for call in scheduler.bus.request.call_args_list if call.args[0].topic == "pool.feedback"]
    assert len(feedback) == 3 and len({message.payload["reservation_id"] for message in feedback}) == 3


@pytest.mark.parametrize("unsubmitted", [0, 1])
async def test_repeated_cancellation_waits_for_save_and_propagates(monkeypatch, unsubmitted):
    started, release, committed = threading.Event(), threading.Event(), threading.Event()

    def save(*_):
        started.set()
        assert release.wait(2)
        committed.set()

    scheduler, domain, recorder = session_scheduler(
        monkeypatch, claimed=1, unsubmitted=unsubmitted, save=save,
        state={"iterations": 15, "halted": True},
    )
    task = asyncio.create_task(scheduler._attempt("case:1", "case"))
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
    assert recorder.finish_invocation.call_args.kwargs["status"] == "error"
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
