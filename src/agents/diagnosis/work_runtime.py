"""诊断会话运行：案例会话自取未承诺案例办理，报告会话收尾，普通程序只管容量与顺序

没有派发单元、没有排队、没有中途补派：若干案例会话各自领取模型池容量并自行
search_cases 取未承诺案例，promise 接手后直接写入完成，搜不到未承诺案例即结束；
全部案例会话结束后，由一个报告会话完成叙事组织与全书报告。
每个会话做完自行保存一次：案例会话存案例产物，报告会话存叙事组织与报告。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from src.event_bus import EventBus, Message
from src.model_pool.capacity import ModelElectionPool
from src.model_pool.contracts import SelectionRequest, SelectionResult

#: 案例会话连续办理的回合上限：会话自行连续办理多个案例，用尽即结束
CASE_SESSION_MAX_ROUNDS = 200

#: 报告会话在模型池中的工作代号
REPORT_SESSION_KEY = "diagnosis-report"


@dataclass
class SessionProgress:
    """会话级内存进度：一个会话一个执行身份，不持久化中途状态"""

    key: str
    role: str
    execution_id: str
    rounds: int = 0
    physical_sequence: int = 0
    audit_sequence: int = 0


@dataclass
class DiagnosisWorkContext:
    """领域按会话角色提供原工具、起始消息与结束检查"""

    program: Any
    initial_messages: list[Any]
    completion_check: Callable[[], list[str]]
    max_rounds: int


class DiagnosisWorkDomain(Protocol):
    """领域只暴露会话上下文、会话保存与报告结果"""

    def build_session_context(self, role: str, execution_id: str, observer: Any) -> DiagnosisWorkContext: ...

    def save_session_progress(self, author: str, role: str) -> None: ...

    def analysis_result(self) -> Any: ...


class DiagnosisWorkScheduler:
    """案例会话并发自取办理；容量沿用模型池既有选举，不另立并发闸"""

    def __init__(
        self, *, run_id: str, domain: DiagnosisWorkDomain, bus: EventBus, model_id: str,
        llm_factory: Callable[[str], Any], observer_factory: Callable[[SessionProgress], Any],
        audit_barrier: Callable[[], Any], is_cancelled: Callable[[], bool] | None = None,
        stream: Any = None, model_retries: int = 1, case_sessions: int | None = None,
    ) -> None:
        self.run_id, self.domain, self.bus = run_id, domain, bus
        self.llm_factory, self.observer_factory = llm_factory, observer_factory
        self.audit_barrier, self.is_cancelled, self.stream = audit_barrier, is_cancelled, stream
        self.model_retries = model_retries
        from src.config import settings
        from src.utils.identity import stable_digest

        self.report_max_rounds = settings.models.diagnosis.max_iterations
        entry = next((item for item in settings.models.model_pool if item.model_id == model_id), None)
        if case_sessions is None:
            # 案例会话数=诊断模型的并发位：会话长活占用容量，不再按案例逐次选举
            case_sessions = int(entry.max_in_flight) if entry is not None else 1
        self.case_sessions = max(1, int(case_sessions))
        self.report_key = stable_digest(self.run_id, REPORT_SESSION_KEY)
        self.pool = ModelElectionPool(bus, run_id, max_attempts=1, fixed_model_id=model_id)
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
                await self.bus.request(Message(
                    topic="pool.feedback", source=f"queue:{self.run_id}", target=self.pool.address,
                    run_id=self.run_id, work_id=selected.work_id,
                    payload={"reservation_id": selected.reservation_id, "outcome": "released"},
                ))
                continue
            if future is None or future.done():
                raise ValueError(f"诊断容量派发没有可接收会话: key={selected.work_id} "
                                 f"waiting={list(self._waiting)} future_done={future.done() if future else None}")
            future.set_result(selected)

    async def _session(self, key: str, role: str) -> None:
        if self.is_cancelled is not None and self.is_cancelled():
            raise asyncio.CancelledError("诊断已取消")
        future: asyncio.Future[SelectionResult] = asyncio.get_running_loop().create_future()
        self._waiting[key] = future
        await self.bus.request(Message(
            topic="pool.enqueue", source=f"queue:{self.run_id}", target=self.pool.address,
            run_id=self.run_id, work_id=key,
            payload=SelectionRequest(self.run_id, key),
        ))
        selected = await future
        self._waiting.pop(key, None)
        progress = SessionProgress(key=key, role=role, execution_id=uuid4().hex)
        observer = self.observer_factory(progress)
        release_capacity = False
        try:
            context = self.domain.build_session_context(role, progress.execution_id, observer)
            llm = self.llm_factory(selected.model_id)
            work_stream = None
            if self.stream is not None:
                from src.agents.stream import AgentStream

                # 流作用域=会话角色（case/report），各会话的并行流由各自 stream_id 区分
                async def emit(event: Any) -> None:
                    event.sub_stage, event.invocation_id = role, progress.execution_id
                    event.stage = "diagnose"
                    await self.stream._emitter(event)

                work_stream = AgentStream(emit, sub_stage=role, stream_id=progress.execution_id)
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
            # 会话做完保存一次：案例与报告产物随各自会话落库，失败轮次不重做已保存内容
            await asyncio.to_thread(self.domain.save_session_progress, progress.execution_id, role)
            # 成功出口同样登记执行终态：执行行不能停在 running 等孤儿清扫反推
            audit_context = getattr(observer, "_context", None)
            if recorder is not None and isinstance(audit_context, dict):
                recorder.finish_invocation(**audit_context, status="success")
                await self.audit_barrier()
            # 回合用尽（halted）不中断整轮：已提交内容保留、未办案例留给其他会话
            release_capacity = True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            recorder = getattr(observer, "_recorder", None)
            audit_context = getattr(observer, "_context", None)
            if recorder is not None and isinstance(audit_context, dict):
                recorder.finish_invocation(**audit_context, status="error", final_error=str(exc))
                await self.audit_barrier()
            progress.physical_sequence = int(getattr(observer, "_turn_counter", progress.physical_sequence))
            progress.audit_sequence = int(getattr(recorder, "sequence", progress.audit_sequence))
            raise
        finally:
            # 只有会话正常结束归还容量；失败与取消由池退出一次性归还
            if release_capacity:
                await self.bus.request(Message(
                    topic="pool.feedback", source=f"queue:{self.run_id}", target=self.pool.address,
                    run_id=self.run_id, work_id=key, invocation_id=progress.execution_id,
                    payload={"reservation_id": selected.reservation_id, "outcome": "released"},
                ))

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
            self.bus.unsubscribe(self.pool.assignment_topic, assignments)

    async def _run_work(self) -> Any:
        await self._wave([(f"case:{index}", "case") for index in range(self.case_sessions)])
        await self._wave([(self.report_key, "report")])
        return self.domain.analysis_result()
