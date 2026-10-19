"""纯内存故障注入覆盖队列取消、模型重选和 work 保存确认边界

内存存储模拟新写面——真实尝试（agent 的 invocation 形状）在派发期由审计登记，
正式产物（agent_annotations）由保存事务写入；保存确认=写事务提交成功，
传输类异常按幂等重存一次。
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
from src.agents.annotation.agent_ir import AgentAnnotation
from src.agents.annotation.errors import AnnotationDependencyError
from src.agents.annotation.ledger import AnnotationToolLedger
from src.case_pool import CasePool
from src.config import settings
from src.event_bus import EventBus, Message
from src.event_trees.trees import EventTrees
from src.fact_graph.graph import FactGraph
from src.model_pool.capacity import MODEL_CAPACITY, ModelElectionExhausted, ModelElectionPool
from src.storage import new_id
from src.work.annotation_work import WorkReceipt
from src.work.chapter_pool import ChapterWorkerPool, PipelineWorkFailed, WorkSaveUnconfirmed


class _MemorySessions:
    """模拟业务保存事务：记录提交/回滚并落正式产物行"""

    def __init__(self) -> None:
        self.executions: dict[str, Any] = {}
        self.products: dict[str, str] = {}
        self.attempt: tuple[str, str] | None = None
        self.product_id = "record"
        self.sessions = 0
        self.commits = 0
        self.fail_commit = 0
        self.fail_after_commit = False
        self.fail_rollback = False
        self.commit_started: threading.Event | None = None
        self.commit_release: threading.Event | None = None

    def expect_attempt(self, work_id: str, invocation_id: str, *, role: str = "entity") -> None:
        """模拟派发期已登记的事实：真实尝试行，以及保存事务将写入的正式产物"""
        self.executions[invocation_id] = SimpleNamespace(
            agent_id=invocation_id, run_id="run", chapter_id=1, role=role
        )
        self.attempt = (work_id, invocation_id)

    def __call__(self) -> Any:
        self.sessions += 1
        owner = self

        class MemoryStorage:
            def __init__(self) -> None:
                self.pending: list[Any] = []

            def save_work(self) -> None:
                self.commit()

            def add(self, row: Any) -> None:
                self.pending.append(row)

            def flush(self) -> None:
                pass

            def commit(self) -> None:
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
                    if table == "agent":
                        owner.executions[row.agent_id] = row
                self.pending = []

            def rollback(self) -> None:
                if owner.fail_rollback:
                    raise ConnectionError("回滚结果不明")
                self.pending = []

            def close(self) -> None:
                pass

            def __enter__(self) -> MemoryStorage:
                return self

            def __exit__(self, *args: Any) -> None:
                self.close()

        return MemoryStorage()


def _receipt(role: str = "entity") -> WorkReceipt:
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
        "src.agents.annotation.agent.build_agent_graph",
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
    for name in ("save", "confirm", "recover", "abort"):

        async def handler(message: Message, name: str = name) -> None:
            calls.append(name)
            if name == "save":
                await asyncio.to_thread(message.payload.save_work)

        bus.handle("agent." + name, "agent:run", handler)


@pytest.mark.asyncio
async def test_cancel_after_real_finish_before_audit_barrier_never_starts_save(monkeypatch: Any) -> None:
    bus, sessions = EventBus(), _MemorySessions()
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
    # 派发期不登记任何 work 行，也从未写入正式产物或取消后补存
    assert not saved and not sessions.products and not sessions.executions
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

    monkeypatch.setattr("src.agents.annotation.agent.build_agent_graph", lambda *args, **kwargs: FailedGraph())
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
    agent = _agent(bus, sessions, monkeypatch)
    for topic, address in (("sse.show", "sse:run"), ("audit.barrier", "audit:run")):
        bus.handle(topic, address, _ignore)
    attempts = []

    class FailedGraph:
        async def ainvoke(self, state: Any, config: Any = None) -> Any:
            attempts.append(1)
            raise AnnotationDependencyError("embedding 服务不可用")

    monkeypatch.setattr("src.agents.annotation.agent.build_agent_graph", lambda *args, **kwargs: FailedGraph())
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
        return {"outcome": "retry" if len(attempts) == 1 else "completed", "invocation_id": new_id()}

    class Pool(ChapterWorkerPool):
        async def _save(self, *args: Any) -> None:
            assert any(MODEL_CAPACITY.snapshot().values())

    monkeypatch.setattr("src.model_pool.selection.select_annotation_model", select)
    monkeypatch.setattr(ModelElectionPool, "feedback", feedback)
    bus.handle("agent.execute", "agent:run", execute)
    bus.handle("agent.cancel", "agent:run", _ignore)
    sessions = _MemorySessions()
    assert await asyncio.wait_for(Pool(poll_seconds=0.005).run([_receipt()], bus=bus, session_factory=sessions), 2) == 1
    assert attempts == [1, 2] and model_failures == [{}, {"test": 1}]
    assert not any(MODEL_CAPACITY.snapshot().values())


@pytest.mark.asyncio
async def test_committed_work_confirmation_recovers_current_author_and_retains_other_claim(monkeypatch: Any) -> None:
    bus, sessions, calls = EventBus(), _MemorySessions(), []
    sessions.expect_attempt("work", "inv")
    agent = _agent(bus, sessions, monkeypatch)
    receipt, author, other = _receipt(), "inv", "other_inv"
    ledger = AnnotationToolLedger(
        run_scope="run",
        current_chapter_id=1,
        current_chapter_text="原文。",
        allow_future_context=False,
        graph=agent.fact_graph,
        work_id="work",
        invocation_id=author,
        role="entity",
    )
    execution = WorkExecution(receipt, author, ledger, AgentAnnotation(role="entity"), finished=True)
    agent.executions["work"] = execution
    for key, sequence in ((author, 1), (other, 2)):
        agent.fact_graph.begin(key, sequence, "entity")
        agent.event_trees.begin(key)
        agent.case_pool.begin(key)
    case = agent.case_pool.push("character", "已核查案例", author)
    agent.case_pool.promise(case["case_id"], author)
    other_case = agent.case_pool.push("character", "其他 work 的案例", other)
    agent.case_pool.promise(other_case["case_id"], other)
    snapshots = (
        {
            "author": author,
            "sequence": 1,
            "role": "entity",
            "entity_ops": [],
            "relation_assert_ops": [],
            "entity_references": [],
        },
        {"author": author, "nodes": {}, "connections": {}},
        {
            "author": author,
            "registrations": {case["case_id"]: case},
            "promises": agent.case_pool.promises_for(author),
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

    def confirm(domain: FactGraph, agent_id: str) -> None:
        nonlocal confirmation_count
        confirmation_count += 1
        calls.append("confirm")
        assert agent.case_pool.case_runtime[case["case_id"]]["owner"] == author
        if confirmation_count == 1:
            raise RuntimeError("内存确认故障")
        original_confirm(agent_id)

    monkeypatch.setattr(FactGraph, "confirm", confirm)
    bus.unhandle("agent.save", "agent:run")
    bus.handle("agent.save", "agent:run", lambda message: asyncio.to_thread(message.payload.save_work))
    await ChapterWorkerPool()._save(bus, "queue:run", receipt, "inv", sessions)
    assert sessions.commits == 1 and confirmation_count == 2 and calls.count("load") == 3
    assert execution.saved and author in agent.fact_graph.saved
    # 确认只标记保存完成：承诺与归属不退回，他方承诺保持
    assert agent.case_pool.case_runtime[case["case_id"]]["owner"] == author
    assert agent.case_pool.case_runtime[other_case["case_id"]]["owner"] == other
    assert other in agent.fact_graph.contributions


@pytest.mark.asyncio
@pytest.mark.parametrize("after_commit", [False, True])
async def test_lost_save_reply_retries_idempotently_on_same_invocation(after_commit: bool) -> None:
    bus, sessions, calls = EventBus(), _MemorySessions(), []
    sessions.expect_attempt("work", "inv")
    _save_handlers(bus, calls)
    sessions.fail_commit, sessions.fail_after_commit = 1, after_commit
    await ChapterWorkerPool()._save(bus, "queue:run", _receipt(), "inv", sessions)
    # 回执丢失后按幂等重存一次：同一 invocation、同一产物行，不重复落
    assert sessions.products == {"inv": "record"}
    assert sessions.commits == 2
    assert calls.count("save") == 2 and calls.count("confirm") == 1 and "abort" not in calls


@pytest.mark.asyncio
async def test_confirmation_exhaustion_marks_work_unconfirmed_without_redispatch(monkeypatch: Any) -> None:
    bus, sessions, calls = EventBus(), _MemorySessions(), []
    sessions.expect_attempt("work", "inv")
    _model_pool(monkeypatch)

    async def execute(message: Message) -> Any:
        return {"outcome": "completed", "invocation_id": "inv"}

    async def cancel(message: Message) -> None:
        assert any(MODEL_CAPACITY.snapshot().values())
        calls.append("cancel")

    async def save(message: Message) -> None:
        calls.append("save")
        await asyncio.to_thread(message.payload.save_work)

    async def confirm(message: Message) -> None:
        calls.append("confirm")
        raise RuntimeError("内存确认故障")

    async def recover(message: Message) -> None:
        calls.append("recover")

    bus.handle("agent.execute", "agent:run", execute)
    bus.handle("agent.cancel", "agent:run", cancel)
    bus.handle("agent.save", "agent:run", save)
    bus.handle("agent.confirm", "agent:run", confirm)
    bus.handle("agent.recover", "agent:run", recover)
    pool = ChapterWorkerPool(poll_seconds=0.005)
    with pytest.raises(WorkSaveUnconfirmed, match="内存确认失败"):
        await asyncio.wait_for(pool.run([_receipt()], bus=bus, session_factory=sessions), 2)
    assert pool.states == {"work": "save_unconfirmed"}
    # 确认两次失败后按未确认收口；队列收尾再对未完成 work 发取消
    assert calls[:4] == ["save", "confirm", "recover", "confirm"]
    assert calls.count("cancel") == 1
    assert sessions.commits == 1 and "abort" not in calls
    assert not any(MODEL_CAPACITY.snapshot().values())


@pytest.mark.asyncio
async def test_failed_rollback_does_not_block_idempotent_retry() -> None:
    bus, sessions, calls = EventBus(), _MemorySessions(), []
    sessions.expect_attempt("work", "inv")
    _save_handlers(bus, calls)
    sessions.fail_commit, sessions.fail_rollback = 1, True
    await ChapterWorkerPool()._save(bus, "queue:run", _receipt(), "inv", sessions)
    # 回滚失败不改变判定：传输类异常仍按幂等重存，第二次提交落定产物
    assert sessions.products == {"inv": "record"}
    assert sessions.commits == 2 and calls.count("save") == 2 and "abort" not in calls
    assert calls.count("confirm") == 1


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
