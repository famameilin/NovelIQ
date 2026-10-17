"""纯内存故障注入覆盖队列取消、模型重选和 work 保存确认边界

2026-10-16 全库 3NF 适配：内存存储模拟新写面——work 身份与真实尝试在派发期
登记，正式产物（chapter_annotations）由保存事务写入；保存核查按
work_items/executions/chapter_annotations 三张真实表判定。
"""

from __future__ import annotations

import asyncio
import threading
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from src.agents.annotation.agent import AnnotationAgent, WorkExecution
from src.agents.annotation.errors import AnnotationDependencyError
from src.agents.annotation.ledger import AnnotationToolLedger
from src.agents.annotation.subagent_ir import SubagentAnnotation
from src.case_pool import CasePool
from src.config import settings
from src.event_bus import EventBus, Message
from src.event_trees.trees import EventTrees
from src.fact_graph.graph import FactGraph
from src.model_pool.capacity import MODEL_CAPACITY, ModelElectionExhausted, ModelElectionPool
from src.work.annotation_work import WorkReceipt
from src.work.chapter_pool import ChapterWorkerPool, PipelineWorkFailed, WorkSaveUnconfirmed


class _MemorySessions:
    """模拟业务事务与新连接核查：按 work_items/executions/chapter_annotations 三表存行"""

    def __init__(self) -> None:
        self.work_items: dict[str, Any] = {}
        self.executions: dict[str, Any] = {}
        self.products: dict[str, str] = {}
        self.attempt: tuple[str, str] | None = None
        self.product_id = "record"
        self.sessions = 0
        self.commits = 0
        # 派发期登记提交的忽略次数（run() 先登记 work 身份，再派发；故障注入只作用于保存提交）
        self.registration_commits = 0
        self.fail_commit = 0
        self.fail_after_commit = False
        self.fail_verification = False
        self.fail_rollback = False
        self.commit_started: threading.Event | None = None
        self.commit_release: threading.Event | None = None

    def expect_attempt(self, work_id: str, invocation_id: str, *, role: str = "structure") -> None:
        """模拟派发期已登记的事实：work 身份、真实尝试行，以及保存事务将写入的正式产物"""
        self.work_items[work_id] = SimpleNamespace(
            work_id=work_id, annotation_run_id="run", annotation_chapter_id=1, role=role
        )
        self.executions[invocation_id] = SimpleNamespace(execution_id=invocation_id, work_id=work_id)
        self.attempt = (work_id, invocation_id)

    def __call__(self) -> Any:
        self.sessions += 1
        owner = self

        class Session:
            def __init__(self) -> None:
                self.pending: list[Any] = []

            def get(self, model: Any, key: str) -> Any:
                if owner.fail_verification and owner.commits:
                    raise ConnectionError("结果核查连接失败")
                table = getattr(model, "__tablename__", "")
                if table == "work_items":
                    return owner.work_items.get(key)
                if table == "executions":
                    return owner.executions.get(key)
                return None

            def add(self, row: Any) -> None:
                self.pending.append(row)

            def flush(self) -> None:
                pass

            def scalar(self, statement: Any) -> Any:
                # stored() 的产物存在性查询：chapter_annotations.record_id where execution_id == ?
                if owner.fail_verification and owner.commits:
                    raise ConnectionError("结果核查连接失败")
                params = statement.compile().params
                invocation_id = next(iter(params.values()), None)
                if "chapter_annotations" not in str(statement):
                    return None
                return owner.products.get(invocation_id)

            def commit(self) -> None:
                if owner.registration_commits > 0:
                    owner.registration_commits -= 1
                    self._write_pending()
                    return
                owner.commits += 1
                if owner.commit_started is not None:
                    owner.commit_started.set()
                if owner.commit_release is not None:
                    assert owner.commit_release.wait(5)
                fails = owner.fail_commit > 0
                owner.fail_commit -= int(fails)
                if fails and not owner.fail_after_commit:
                    raise OSError("提交前连接中断")
                if owner.attempt is not None:
                    owner.products[owner.attempt[1]] = owner.product_id
                self._write_pending()
                if fails:
                    raise OSError("提交回执丢失")

            def _write_pending(self) -> None:
                for row in self.pending:
                    table = getattr(type(row), "__tablename__", "")
                    if table == "work_items":
                        owner.work_items[row.work_id] = row
                    elif table == "executions":
                        owner.executions[row.execution_id] = row
                self.pending = []

            def rollback(self) -> None:
                if owner.fail_rollback:
                    raise ConnectionError("回滚结果不明")
                self.pending = []

            def close(self) -> None:
                pass

            def __enter__(self) -> Session:
                return self

            def __exit__(self, *args: Any) -> None:
                self.close()

        return Session()


def _receipt(role: str = "structure") -> WorkReceipt:
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
            "role": role,
            "paragraphs": [
                SimpleNamespace(chapter_id=1, paragraph_id=1, local_start_char=0, local_end_char=3, text="原文。")
            ],
            "model_id": "test",
            "attempt_number": 1,
            "reservation_id": "reservation",
        },
    )


def _model_pool(monkeypatch: Any) -> None:
    monkeypatch.setattr(settings.models, "model_pool", [SimpleNamespace(model_id="test", max_in_flight=1, weight=1)])
    monkeypatch.setattr("src.model_pool.selection.select_annotation_model", lambda *args, **kwargs: "test")


class _NoDatabaseAudit:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __getattr__(self, name: str) -> Any:
        return lambda *args, **kwargs: 1


class _FinishGraph:
    def __init__(self, program: Any, completion_check: Any) -> None:
        self.program = program
        self.completion_check = completion_check

    async def ainvoke(self, state: Any, config: Any = None) -> dict[str, Any]:
        await self.program.ainvoke({"code": "finish()"})
        assert self.completion_check() == []
        return {"error": None}


def _agent(bus: EventBus, sessions: Any, monkeypatch: Any) -> AnnotationAgent:
    monkeypatch.setattr("src.agents.annotation.agent.AuditMessages", _NoDatabaseAudit)
    monkeypatch.setattr("src.agents.annotation.agent.AgentTurnObserver", _NoDatabaseAudit)
    monkeypatch.setattr(
        "src.model_pool.llm.build_chat_model",
        lambda *args, **kwargs: SimpleNamespace(model_name="fake"),
    )
    monkeypatch.setattr("src.model_pool.configuration.load_task_config", lambda *args, **kwargs: None)
    monkeypatch.setattr("src.embedding.EmbeddingClient", lambda **kwargs: object())
    monkeypatch.setattr(
        "src.agents.annotation.queries.DatabaseAnnotationQueryService", lambda *args, **kwargs: object()
    )
    monkeypatch.setattr(
        "src.agents.annotation.agent.build_subagent_graph",
        lambda model, program, *args, **kwargs: _FinishGraph(program, kwargs["completion_check"]),
    )
    return AnnotationAgent(
        bus,
        "run",
        sessions,
        novel_id="test",
        fact_graph=FactGraph(run_scope="run"),
        event_trees=EventTrees("run"),
        case_pool=CasePool("run"),
    )


async def _ignore(message: Message) -> None:
    pass


def _save_handlers(bus: EventBus, calls: list[str]) -> None:
    for name in ("save", "check", "confirm", "recover", "abort"):

        async def handler(message: Message, name: str = name) -> Any:
            calls.append(name)
            return True if name == "check" else None

        bus.handle("agent." + name, "agent:run", handler)


@pytest.mark.asyncio
async def test_cancel_after_real_finish_before_audit_barrier_never_starts_save(monkeypatch: Any) -> None:
    bus, sessions = EventBus(), _MemorySessions()
    sessions.registration_commits = 1
    agent = _agent(bus, sessions, monkeypatch)
    _model_pool(monkeypatch)
    waiting, cancelled_message, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    cancelled = False
    saved: list[bool] = []

    async def barrier(message: Message) -> None:
        assert agent.executions["work"].finished
        waiting.set()
        await release.wait()

    async def cancel(message: Message) -> None:
        await agent.cancel(message)
        cancelled_message.set()

    class Pool(ChapterWorkerPool):
        async def _save(self, *args: Any) -> None:
            saved.append(True)

    bus.handle("sse.show", "sse:run", _ignore)
    bus.handle("audit.barrier", "audit:run", barrier)
    bus.unhandle("agent.cancel", "agent:run")
    bus.handle("agent.cancel", "agent:run", cancel)
    task = asyncio.create_task(
        Pool(poll_seconds=0.005).run([_receipt()], bus=bus, session_factory=sessions, is_cancelled=lambda: cancelled)
    )
    await asyncio.wait_for(waiting.wait(), 2)
    cancelled = True
    await asyncio.wait_for(cancelled_message.wait(), 2)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    # 派发期已登记 work 身份，但从未写入任何正式产物或取消后补存
    assert not saved and not sessions.products
    assert [row.role for row in sessions.work_items.values()] == ["structure"]
    assert not agent.fact_graph.contributions and not agent.case_pool.cases
    assert not any(MODEL_CAPACITY.snapshot().values())


@pytest.mark.asyncio
async def test_completed_reply_cannot_start_new_save_after_cancel() -> None:
    bus, sessions, calls = EventBus(), _MemorySessions(), []
    _save_handlers(bus, calls)
    with pytest.raises(asyncio.CancelledError):
        await ChapterWorkerPool()._save(bus, "queue:run", _receipt(), "inv", sessions, lambda: False)
    assert calls == ["abort"] and sessions.sessions == 0


@pytest.mark.asyncio
async def test_cancel_during_commit_retains_original_save_and_confirmation(monkeypatch: Any) -> None:
    bus, sessions, calls = EventBus(), _MemorySessions(), []
    sessions.expect_attempt("work", "inv")
    sessions.registration_commits = 1
    _model_pool(monkeypatch)
    _save_handlers(bus, calls)
    sessions.commit_started, sessions.commit_release = threading.Event(), threading.Event()
    cancelled_message = asyncio.Event()
    cancelled = False

    async def execute(message: Message) -> Any:
        return {"outcome": "completed", "invocation_id": "inv"}

    async def cancel(message: Message) -> None:
        calls.append("cancel")
        cancelled_message.set()

    bus.handle("agent.execute", "agent:run", execute)
    bus.handle("agent.cancel", "agent:run", cancel)
    task = asyncio.create_task(
        ChapterWorkerPool(poll_seconds=0.005).run(
            [_receipt()], bus=bus, session_factory=sessions, is_cancelled=lambda: cancelled
        )
    )
    assert await asyncio.to_thread(sessions.commit_started.wait, 2)
    cancelled = True
    await asyncio.wait_for(cancelled_message.wait(), 2)
    sessions.commit_release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert sessions.commits == 1 and sessions.products == {"inv": "record"}
    assert calls.count("save") == calls.count("confirm") == 1 and "abort" not in calls
    assert not any(MODEL_CAPACITY.snapshot().values())


@pytest.mark.asyncio
async def test_provider_timeout_returns_retry_with_own_contributions_removed(monkeypatch: Any) -> None:
    bus = EventBus()
    agent = _agent(bus, _MemorySessions(), monkeypatch)
    for topic, address in (("queue.started", "queue:run"), ("sse.show", "sse:run"), ("audit.barrier", "audit:run")):
        bus.handle(topic, address, _ignore)

    class FailedGraph:
        async def ainvoke(self, state: Any, config: Any = None) -> Any:
            raise TimeoutError("供应商请求重试耗尽")

    monkeypatch.setattr("src.agents.annotation.agent.build_subagent_graph", lambda *args, **kwargs: FailedGraph())
    result = await agent.execute(
        Message("agent.execute", "queue:run", "agent:run", "run", work_id="work", payload=_receipt())
    )
    assert result["outcome"] == "retry" and result["invocation_id"]
    assert not agent.fact_graph.contributions and not agent.event_trees.nodes and not agent.case_pool.cases


@pytest.mark.asyncio
async def test_dependency_failure_is_not_model_retry_and_stops_work_pool(monkeypatch: Any) -> None:
    """依赖故障上抛终止队列，只派发一次、不保存 work、不遗留模型容量"""
    bus = EventBus()
    _model_pool(monkeypatch)
    sessions = _MemorySessions()
    sessions.registration_commits = 1
    agent = _agent(bus, sessions, monkeypatch)
    for topic, address in (("sse.show", "sse:run"), ("audit.barrier", "audit:run")):
        bus.handle(topic, address, _ignore)
    attempts = []

    class FailedGraph:
        async def ainvoke(self, state: Any, config: Any = None) -> Any:
            attempts.append(1)
            raise AnnotationDependencyError("embedding 服务不可用")

    monkeypatch.setattr("src.agents.annotation.agent.build_subagent_graph", lambda *args, **kwargs: FailedGraph())
    with pytest.raises(AnnotationDependencyError, match="embedding 服务不可用"):
        await ChapterWorkerPool().run([_receipt()], bus=bus, session_factory=sessions)
    assert attempts == [1]
    assert not sessions.products
    assert not agent.fact_graph.contributions and not agent.event_trees.nodes and not agent.case_pool.cases
    assert not any(MODEL_CAPACITY.snapshot().values())


@pytest.mark.asyncio
async def test_retry_feedback_preserves_pool_failure_weight_before_reselection(monkeypatch: Any) -> None:
    bus, model_failures, attempts = EventBus(), [], []
    _model_pool(monkeypatch)
    original_feedback = ModelElectionPool.feedback

    def select(*args: Any, **kwargs: Any) -> str:
        model_failures.append(dict(kwargs["failures"]))
        return "test"

    async def feedback(pool: ModelElectionPool, message: Message) -> Any:
        await original_feedback(pool, message)
        pool.available_at[message.work_id] = 0

    async def execute(message: Message) -> Any:
        attempts.append(message.payload.payload["attempt_number"])
        return {"outcome": "retry" if len(attempts) == 1 else "completed", "invocation_id": f"inv{len(attempts)}"}

    class Pool(ChapterWorkerPool):
        async def _save(self, *args: Any) -> None:
            assert any(MODEL_CAPACITY.snapshot().values())

    monkeypatch.setattr("src.model_pool.selection.select_annotation_model", select)
    monkeypatch.setattr(ModelElectionPool, "feedback", feedback)
    bus.handle("agent.execute", "agent:run", execute)
    bus.handle("agent.cancel", "agent:run", _ignore)
    sessions = _MemorySessions()
    sessions.registration_commits = 1
    assert (
        await asyncio.wait_for(Pool(poll_seconds=0.005).run([_receipt()], bus=bus, session_factory=sessions), 2) == 1
    )
    assert attempts == [1, 2] and model_failures == [{}, {"test": 1}]
    assert not any(MODEL_CAPACITY.snapshot().values())


@pytest.mark.asyncio
async def test_committed_work_confirmation_recovers_current_author_and_retains_other_claim(monkeypatch: Any) -> None:
    bus, sessions, calls = EventBus(), _MemorySessions(), []
    sessions.expect_attempt("work", "inv")
    agent = _agent(bus, sessions, monkeypatch)
    receipt, author, other = _receipt(), ("work", "inv"), ("other", "other_inv")
    ledger = AnnotationToolLedger(
        run_scope="run",
        current_chapter_id=1,
        current_chapter_text="原文。",
        allow_future_context=False,
        graph=agent.fact_graph,
        work_id=author[0],
        invocation_id=author[1],
        role="structure",
    )
    execution = WorkExecution(receipt, "inv", ledger, SubagentAnnotation(role="structure"), finished=True)
    agent.executions["work"] = execution
    for key, sequence in ((author, 1), (other, 2)):
        agent.fact_graph.begin(*key, sequence, "structure")
        agent.event_trees.begin(*key)
        agent.case_pool.begin(*key)
    case = agent.case_pool.push("character", "已核查案例", author)
    agent.case_pool.promise(case["case_id"], author)
    agent.case_pool.associate(
        case["case_id"],
        author,
        call_id="write-1",
        tool_name="write_entity",
        receipt={"status": "written"},
        is_write=True,
    )
    other_case = agent.case_pool.push("character", "其他 work 的案例", other)
    agent.case_pool.promise(other_case["case_id"], other)
    snapshots = (
        {
            "author": author,
            "sequence": 1,
            "role": "structure",
            "entity_ops": [],
            "relation_assert_ops": [],
            "entity_references": [],
        },
        {"author": author, "nodes": {}, "connections": {}},
        {
            "author": author,
            "registrations": {case["case_id"]: case},
            "deliveries": deepcopy(agent.case_pool.deliveries[author]),
        },
    )
    for domain, snapshot in zip((agent.fact_graph, agent.event_trees, agent.case_pool), snapshots, strict=True):

        def load(*args: Any, snapshot: Any = snapshot) -> Any:
            assert not agent.lock.locked()
            calls.append("load")
            return deepcopy(snapshot)

        monkeypatch.setattr(type(domain), "load_saved_work", load)
    original_confirm = agent.fact_graph.confirm
    confirmation_count = 0

    def confirm(domain: FactGraph, work_id: str, invocation_id: str) -> None:
        nonlocal confirmation_count
        confirmation_count += 1
        calls.append("confirm")
        assert agent.case_pool.case_runtime[case["case_id"]]["owner"] == author
        if confirmation_count == 1:
            raise RuntimeError("内存确认故障")
        original_confirm(work_id, invocation_id)

    async def check(message: Message) -> bool:
        return True

    monkeypatch.setattr(FactGraph, "confirm", confirm)
    monkeypatch.setattr(agent, "check", check)
    bus.unhandle("agent.check", "agent:run")
    bus.handle("agent.check", "agent:run", check)
    bus.unhandle("agent.save", "agent:run")
    bus.handle("agent.save", "agent:run", _ignore)
    await ChapterWorkerPool()._save(bus, "queue:run", receipt, "inv", sessions)
    assert sessions.commits == 1 and confirmation_count == 2 and calls.count("load") == 3
    assert execution.saved and author in agent.fact_graph.saved
    assert agent.case_pool.case_runtime[case["case_id"]]["owner"] is None
    assert agent.case_pool.case_runtime[other_case["case_id"]]["owner"] == other
    assert other in agent.fact_graph.contributions


@pytest.mark.asyncio
@pytest.mark.parametrize("after_commit", [False, True])
async def test_lost_save_reply_reuses_original_invocation_without_duplicate_commit(after_commit: bool) -> None:
    bus, sessions, calls = EventBus(), _MemorySessions(), []
    sessions.expect_attempt("work", "inv")
    _save_handlers(bus, calls)
    sessions.fail_commit, sessions.fail_after_commit = 1, after_commit
    await ChapterWorkerPool()._save(bus, "queue:run", _receipt(), "inv", sessions)
    assert sessions.products == {"inv": "record"}
    assert sessions.commits == (1 if after_commit else 2)
    assert calls.count("save") == (1 if after_commit else 2)
    assert calls.count("confirm") == 1 and "abort" not in calls


@pytest.mark.asyncio
async def test_unknown_commit_or_failed_verification_keeps_contributions_and_capacity(monkeypatch: Any) -> None:
    bus, sessions, calls = EventBus(), _MemorySessions(), []
    sessions.expect_attempt("work", "inv")
    sessions.registration_commits = 1
    _model_pool(monkeypatch)
    _save_handlers(bus, calls)
    sessions.fail_commit, sessions.fail_after_commit, sessions.fail_verification = 1, True, True

    async def execute(message: Message) -> Any:
        return {"outcome": "completed", "invocation_id": "inv"}

    async def cancel(message: Message) -> None:
        assert any(MODEL_CAPACITY.snapshot().values())
        calls.append("cancel")

    bus.handle("agent.execute", "agent:run", execute)
    bus.handle("agent.cancel", "agent:run", cancel)
    pool = ChapterWorkerPool(poll_seconds=0.005)
    with pytest.raises(WorkSaveUnconfirmed, match="核查失败"):
        await asyncio.wait_for(pool.run([_receipt()], bus=bus, session_factory=sessions), 2)
    assert pool.states == {"work": "save_unconfirmed"}
    assert "abort" not in calls and "confirm" not in calls and calls.count("save") == 1
    assert not any(MODEL_CAPACITY.snapshot().values())


@pytest.mark.asyncio
async def test_failed_rollback_and_missing_row_are_not_treated_as_confirmed_unsaved() -> None:
    bus, sessions, calls = EventBus(), _MemorySessions(), []
    _save_handlers(bus, calls)
    sessions.fail_commit, sessions.fail_rollback = 1, True
    with pytest.raises(WorkSaveUnconfirmed, match="仍不明"):
        await ChapterWorkerPool()._save(bus, "queue:run", _receipt(), "inv", sessions)
    assert "abort" not in calls and sessions.commits == 1


@pytest.mark.asyncio
async def test_existing_immutable_work_conflict_is_not_overwritten_or_aborted() -> None:
    bus, sessions, calls = EventBus(), _MemorySessions(), []
    _save_handlers(bus, calls)
    # 派发期身份登记是幂等的；此处模拟同 work_id 落着另一份不可变身份
    sessions.work_items["work"] = SimpleNamespace(
        work_id="work", annotation_run_id="other_run", annotation_chapter_id=9, role="event"
    )
    sessions.executions["inv"] = SimpleNamespace(execution_id="inv", work_id="work")
    with pytest.raises(WorkSaveUnconfirmed, match="存储冲突"):
        await ChapterWorkerPool()._save(bus, "queue:run", _receipt(), "inv", sessions)
    assert "abort" not in calls
    assert sessions.work_items["work"].role == "event"
    assert sessions.work_items["work"].annotation_chapter_id == 9


@pytest.mark.asyncio
async def test_model_pool_exhaustion_never_sends_cancel_after_termination(monkeypatch: Any) -> None:
    bus, actions = EventBus(), []
    _model_pool(monkeypatch)
    original_run, original_feedback = ModelElectionPool.run, ModelElectionPool.feedback

    async def run(pool: ModelElectionPool) -> None:
        try:
            await original_run(pool)
        except ModelElectionExhausted:
            actions.append("pool_ended")
            raise

    async def feedback(pool: ModelElectionPool, message: Message) -> None:
        await original_feedback(pool, message)
        pool.available_at[message.work_id] = 0

    async def execute(message: Message) -> Any:
        return {"outcome": "retry", "invocation_id": "inv"}

    async def cancel(message: Message) -> None:
        actions.append("cancel_after_pool_end")

    monkeypatch.setattr(ModelElectionPool, "run", run)
    monkeypatch.setattr(ModelElectionPool, "feedback", feedback)
    bus.handle("agent.execute", "agent:run", execute)
    bus.handle("agent.cancel", "agent:run", cancel)
    sessions = _MemorySessions()
    sessions.registration_commits = 1
    with pytest.raises(ModelElectionExhausted):
        await asyncio.wait_for(
            ChapterWorkerPool(max_attempts=1, poll_seconds=0.005).run([_receipt()], bus=bus, session_factory=sessions),
            2,
        )
    assert actions == ["pool_ended"] and not any(MODEL_CAPACITY.snapshot().values())


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_mode", ["normal", "error"])
async def test_any_model_pool_exit_avoids_post_termination_cancel(monkeypatch: Any, exit_mode: str) -> None:
    bus, actions = EventBus(), []
    _model_pool(monkeypatch)
    original_run, original_feedback = ModelElectionPool.run, ModelElectionPool.feedback

    async def run(pool: ModelElectionPool) -> None:
        try:
            await original_run(pool)
        except ModelElectionExhausted:
            actions.append("pool_ended")
            if exit_mode == "error":
                raise ValueError("模型池配置故障") from None

    async def feedback(pool: ModelElectionPool, message: Message) -> None:
        await original_feedback(pool, message)
        pool.available_at[message.work_id] = 0

    async def execute(message: Message) -> Any:
        return {"outcome": "retry", "invocation_id": "inv"}

    async def cancel(message: Message) -> None:
        actions.append("cancel_after_pool_end")

    monkeypatch.setattr(ModelElectionPool, "run", run)
    monkeypatch.setattr(ModelElectionPool, "feedback", feedback)
    bus.handle("agent.execute", "agent:run", execute)
    bus.handle("agent.cancel", "agent:run", cancel)
    sessions = _MemorySessions()
    sessions.registration_commits = 1
    with pytest.raises(ValueError if exit_mode == "error" else PipelineWorkFailed):
        await asyncio.wait_for(
            ChapterWorkerPool(max_attempts=1, poll_seconds=0.005).run([_receipt()], bus=bus, session_factory=sessions),
            2,
        )
    assert actions == ["pool_ended"] and not any(MODEL_CAPACITY.snapshot().values())


@pytest.mark.asyncio
async def test_model_ended_before_save_does_not_send_abort_or_open_transaction() -> None:
    bus, sessions, calls = EventBus(), _MemorySessions(), []
    _save_handlers(bus, calls)
    with pytest.raises(asyncio.CancelledError):
        await ChapterWorkerPool()._save(bus, "queue:run", _receipt(), "inv", sessions, lambda: True, lambda: True)
    assert not calls and sessions.sessions == 0


@pytest.mark.asyncio
async def test_pool_configuration_fault_waits_for_reserved_work_save_before_exit(monkeypatch: Any) -> None:
    bus, actions = EventBus(), []
    _model_pool(monkeypatch)
    selection_failed, executing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    elections = 0

    def select(*args: Any, **kwargs: Any) -> str:
        nonlocal elections
        elections += 1
        if elections > 1:
            selection_failed.set()
            raise ValueError("模型池配置故障")
        return "test"

    async def execute(message: Message) -> Any:
        executing.set()
        await release.wait()
        return {"outcome": "completed", "invocation_id": "inv"}

    async def cancel(message: Message) -> None:
        actions.append("cancel")

    class Pool(ChapterWorkerPool):
        async def _save(self, *args: Any) -> None:
            assert any(MODEL_CAPACITY.snapshot().values())
            actions.append("save")

    monkeypatch.setattr("src.model_pool.selection.select_annotation_model", select)
    bus.handle("agent.execute", "agent:run", execute)
    bus.handle("agent.cancel", "agent:run", cancel)
    sessions = _MemorySessions()
    sessions.registration_commits = 1
    task = asyncio.create_task(
        Pool(poll_seconds=0.005).run(
            [_receipt(), replace(_receipt(), work_id="other")], bus=bus, session_factory=sessions
        )
    )
    await asyncio.wait_for(selection_failed.wait(), 2)
    await asyncio.wait_for(executing.wait(), 2)
    assert not task.done() and any(MODEL_CAPACITY.snapshot().values())
    release.set()
    with pytest.raises(ValueError, match="模型池配置故障"):
        await asyncio.wait_for(task, 2)
    assert actions == ["save"] and elections == 2
    assert not any(MODEL_CAPACITY.snapshot().values())
