"""按待领数量补位案例会话，全部保存后启动报告会话"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from src.agents.annotation.errors import AnnotationBudgetExhaustedError
from src.agents.stream import ModelRequestError
from src.event_bus import EventBus, Message
from src.event_bus.notifications import StreamEvent
from src.model_pool.capacity import ModelElectionPool
from src.model_pool.configuration import model_context_window
from src.model_pool.contracts import SelectionRequest, SelectionResult
from src.storage import new_id

#: 报告会话在模型池中的工作代号
REPORT_SESSION_KEY = "diagnosis-report"


@dataclass
class SessionProgress:
    """会话级内存进度：一个会话一个执行身份，不持久化中途状态"""

    key: str
    role: str
    agent_id: str
    rounds: int = 0
    physical_sequence: int = 0
    audit_sequence: int = 0
    model_id: str = ""
    attempt_number: int = 1


@dataclass
class DiagnosisWorkContext:
    """领域按会话角色提供原工具、起始消息与结束检查"""

    program: Any
    initial_messages: list[Any]
    completion_check: Callable[[], list[str]]
    max_rounds: int
    claimed_count: Callable[[], int] = lambda: 0
    unsubmitted_count: Callable[[], int] = lambda: 0


class DiagnosisWorkDomain(Protocol):
    """领域只暴露会话上下文、案例池进度、会话保存与报告结果"""

    def build_session_context(self, role: str, agent_id: str, observer: Any) -> DiagnosisWorkContext: ...

    def case_counts(self) -> tuple[int, int]: ...

    def save_session_progress(self, author: str, role: str) -> None: ...

    def analysis_result(self) -> Any: ...


class DiagnosisWorkScheduler:
    """案例会话按池内并发位自取办理，模型按会话选举；报告会话用指定诊断模型"""

    def __init__(
        self,
        *,
        run_id: str,
        domain: DiagnosisWorkDomain,
        bus: EventBus,
        model_id: str | None,
        llm_factory: Callable[[str], Any],
        observer_factory: Callable[[SessionProgress], Any],
        audit_barrier: Callable[[], Any],
        is_cancelled: Callable[[], bool] | None = None,
        stream: Any = None,
        model_retries: int = 1,
        case_sessions: int | None = None,
    ) -> None:
        self.run_id, self.domain, self.bus = run_id, domain, bus
        self.llm_factory, self.observer_factory = llm_factory, observer_factory
        self.audit_barrier, self.is_cancelled, self.stream = audit_barrier, is_cancelled, stream
        self.model_retries = model_retries
        from src.config import settings
        from src.utils.identity import stable_digest

        self.report_max_rounds = settings.models.diagnosis.max_iterations
        if case_sessions is None:
            # 案例会话数=池内并发位之和：每个长活会话占一个容量位
            case_sessions = sum(int(item.max_in_flight) for item in settings.models.model_pool if item.weight > 0)
        self.case_sessions = max(1, int(case_sessions))
        self.model_id = model_id
        self.report_key = stable_digest(self.run_id, REPORT_SESSION_KEY)
        self.pool = ModelElectionPool(bus, run_id)
        self._waiting: dict[str, asyncio.Future[SelectionResult]] = {}

    async def _assignments(self, queue: Any) -> None:
        while True:
            message = await queue.get()
            selected = message.payload
            if not isinstance(selected, SelectionResult) or selected.run_id != self.run_id:
                raise ValueError("诊断选举返回身份不一致")
            future = self._waiting.get(selected.work_id)
            if future is not None and future.cancelled():
                # 会话失败会取消仍在排队的兄弟，归还已经派发但尚未领取的容量
                self._waiting.pop(selected.work_id, None)
                await self.bus.request(
                    Message(
                        topic="pool.feedback",
                        source=f"queue:{self.run_id}",
                        target=self.pool.address,
                        run_id=self.run_id,
                        work_id=selected.work_id,
                        payload={"reservation_id": selected.reservation_id, "outcome": "released"},
                    )
                )
                continue
            if future is None or future.done():
                raise ValueError(
                    f"诊断容量派发没有可接收会话: key={selected.work_id} "
                    f"waiting={list(self._waiting)} future_done={future.done() if future else None}"
                )
            future.set_result(selected)

    async def _session(self, key: str, role: str) -> None:
        """同一工作按模型池结果重试，每次尝试使用独立执行身份"""
        while await self._attempt(key, role):
            pass

    async def _attempt(self, key: str, role: str) -> bool:
        """执行一次选举派发，返回是否需要重新选举"""
        if self.is_cancelled is not None and self.is_cancelled():
            raise asyncio.CancelledError("诊断已取消")
        future: asyncio.Future[SelectionResult] = asyncio.get_running_loop().create_future()
        self._waiting[key] = future
        queued_ns = time.perf_counter_ns()
        selected: SelectionResult | None = None
        progress: SessionProgress | None = None
        observer: Any = None
        saved = False
        incomplete_error: AnnotationBudgetExhaustedError | None = None
        retry = False
        timings: dict[str, float] = {}

        async def finish(status: str, error: str | None = None) -> None:
            recorder = getattr(observer, "_recorder", None)
            audit_context = getattr(observer, "_context", None)
            if recorder is not None and isinstance(audit_context, dict):
                recorder.finish_invocation(
                    **audit_context, status=status, final_error=error, runtime_timings=timings,
                )
                await self.audit_barrier()

        try:
            await self.bus.request(
                Message(topic="pool.enqueue", source=f"queue:{self.run_id}", target=self.pool.address,
                        run_id=self.run_id, work_id=key,
                        payload=SelectionRequest(self.run_id, key,
                                                 fixed_model_id=self.model_id if role == "report" else None))
            )
            selected = await future
            self._waiting.pop(key, None)
            timings["queue_wait_ms"] = round((time.perf_counter_ns() - queued_ns) / 1_000_000, 3)
            if role == "case" and self.domain.case_counts()[0] == 0:
                return False
            progress = SessionProgress(key=key, role=role, agent_id=new_id(), model_id=selected.model_id,
                                       attempt_number=selected.attempt_number)
            session_model_id = selected.model_id
            session_reservation_id = selected.reservation_id

            async def activity(event: StreamEvent) -> None:
                event.stage, event.sub_stage = "diagnose", role
                event.model_id, event.reservation_id = session_model_id, session_reservation_id
                case_pool = getattr(self.domain, "case_pool", None)
                if case_pool is not None and role == "case":
                    event.details = {"case_ids": case_pool.claims_for(progress.agent_id),
                        "unsubmitted_case_ids": case_pool.unsubmitted_for(progress.agent_id)}
                if self.bus.has_handler("analysis.activity", f"activity:{self.run_id}"):
                    await self.bus.deliver(Message(topic="analysis.activity", source="diagnosis",
                        target=f"activity:{self.run_id}", run_id=self.run_id, work_id=key,
                        invocation_id=progress.agent_id, payload=event))

            await activity(StreamEvent(action="activity", activity="starting"))
            observer = self.observer_factory(progress)
            context = self.domain.build_session_context(role, progress.agent_id, observer)
            llm = self.llm_factory(selected.model_id)
            context_window_tokens = model_context_window(selected.model_id)
            work_stream = None
            if self.stream is not None:
                from src.agents.stream import AgentStream

                # 流作用域=会话角色（case/report），各会话的并行流由各自 stream_id 区分
                async def emit(event: Any) -> None:
                    await activity(event)

                work_stream = AgentStream(emit, sub_stage=role, stream_id=progress.agent_id)
            # 会话图按标注三节点族构建（复用 annotation/agent_graph 的同一图结构）
            from src.agents.annotation.agent_graph import build_agent_graph
            from src.agents.annotation.agent_ir import AgentAnnotation
            from src.agents.annotation.ledger import AnnotationToolLedger

            from .program_runtime import bind_finish_ledger

            ledger = AnnotationToolLedger(
                run_scope=self.run_id, current_chapter_id=0, current_chapter_text="", allow_future_context=False
            )
            graph = build_agent_graph(
                llm,
                context.program.build_tool(),
                bind_finish_ledger(context.program.tools["finish"], ledger),
                ledger=ledger,
                agent=AgentAnnotation(role=role),
                max_iterations=context.max_rounds,
                context_window_tokens=context_window_tokens,
                stream=work_stream,
                observer=observer,
                retries=self.model_retries,
                completion_check=context.completion_check,
                thinking_message=lambda rounds: f"诊断推理中（第 {rounds} 轮）...",
            )
            final_state = await graph.ainvoke(
                {
                    "messages": list(context.initial_messages),
                    "phase": "chapter_open",
                    "iterations": progress.rounds,
                    "error": None,
                },
                config={"recursion_limit": 4 * context.max_rounds + 10},
            )
            progress.rounds = int(final_state.get("iterations") or progress.rounds)
            progress.physical_sequence = int(getattr(observer, "_turn_counter", progress.physical_sequence))
            recorder = getattr(observer, "_recorder", None)
            progress.audit_sequence = int(getattr(recorder, "sequence", progress.audit_sequence))
            if final_state.get("error"):
                raise RuntimeError(str(final_state["error"]))
            if final_state.get("halted"):
                incomplete_error = AnnotationBudgetExhaustedError("会话回合已耗尽，交回模型池重新选举")
                if role != "case" or context.claimed_count() == 0:
                    raise incomplete_error
            if role == "case" and context.unsubmitted_count() and incomplete_error is None:
                raise RuntimeError("完整性检查已结束但仍有未提交领取")
            await self.audit_barrier()
            await activity(StreamEvent(action="activity", activity="saving"))
            started_ns = time.perf_counter_ns()
            transaction = asyncio.create_task(
                asyncio.to_thread(self.domain.save_session_progress, progress.agent_id, role)
            )
            cancellation: asyncio.CancelledError | None = None
            try:
                while True:
                    try:
                        await asyncio.shield(transaction)
                        break
                    except asyncio.CancelledError as exc:
                        cancellation = exc
            finally:
                timings["save_ms"] = round((time.perf_counter_ns() - started_ns) / 1_000_000, 3)
            saved = True
            await activity(StreamEvent(action="work_saved"))
            if cancellation is not None:
                raise cancellation
            if incomplete_error is not None:
                raise incomplete_error
        except BaseException as exc:
            if progress is not None:
                await activity(
                    StreamEvent(
                        action="activity",
                        activity="cancelled" if isinstance(exc, asyncio.CancelledError) else "error",
                        message=str(exc),
                    )
                )
            if progress is not None and not saved:
                abort = getattr(self.domain, "abort_session", None)
                if abort is not None:
                    abort(progress.agent_id)
            successful = saved and incomplete_error is None
            await finish("success" if successful else "error", None if successful else str(exc) or type(exc).__name__)
            if isinstance(exc, (ModelRequestError, AnnotationBudgetExhaustedError)):
                await activity(StreamEvent(action="activity", activity="retry", message="等待模型池重新选举"))
                retry = True
                return True
            raise
        else:
            await finish("success")
            return False
        finally:
            if selected is None and future.done() and not future.cancelled():
                selected = future.result()
            if selected is not None:
                self._waiting.pop(key, None)
                await self.bus.request(
                    Message(
                        topic="pool.feedback",
                        source=f"queue:{self.run_id}",
                        target=self.pool.address,
                        run_id=self.run_id,
                        work_id=key,
                        invocation_id=progress.agent_id if progress is not None else "",
                        payload={"reservation_id": selected.reservation_id,
                                 "outcome": "retry" if retry else "released"},
                    )
                )

    async def _wave(self, sessions: list[tuple[str, str]]) -> None:
        tasks = [asyncio.create_task(self._session(key, role)) for key, role in sessions]
        try:
            await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    async def run(self) -> Any:
        assignments = self.bus.subscribe(self.pool.assignment_topic)
        pool_task = asyncio.create_task(self.pool.run())
        assignments_task = asyncio.create_task(self._assignments(assignments))
        work_task = asyncio.create_task(self._run_work())
        try:
            done, _ = await asyncio.wait({pool_task, assignments_task, work_task}, return_when=asyncio.FIRST_COMPLETED)
            for task in (pool_task, assignments_task):
                if task in done:
                    await task
                    raise RuntimeError("诊断模型池意外退出")
            return await work_task
        finally:
            self.pool.stop_elections()
            for task in (work_task, pool_task, assignments_task):
                task.cancel()
            await asyncio.gather(work_task, pool_task, assignments_task, return_exceptions=True)
            self.pool.close()
            await self.pool.notify_capacity()
            self._waiting.clear()
            self.bus.unsubscribe(self.pool.assignment_topic, assignments)

    async def _run_work(self) -> Any:
        tasks: set[asyncio.Task[None]] = set()
        serial = 0
        try:
            while True:
                available = min(self.case_sessions - len(tasks), self.domain.case_counts()[0])
                for _ in range(available):
                    serial += 1
                    tasks.add(asyncio.create_task(self._session(f"case:{serial}", "case")))
                if not tasks:
                    break
                done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                results = await asyncio.gather(*done, return_exceptions=True)
                errors = [result for result in results if isinstance(result, BaseException)]
                if len(errors) == 1:
                    raise errors[0]
                if errors:
                    raise BaseExceptionGroup("案例会话同时失败", errors)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        if self.domain.case_counts()[0]:
            raise RuntimeError("案例池仍有待领案例，禁止启动报告")
        await self._wave([(self.report_key, "report")])
        return self.domain.analysis_result()
