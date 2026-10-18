"""诊断案例派发与领域适配协议，领域写入不由编排程序代办"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from src.event_bus import EventBus, Message
from src.model_pool.capacity import ModelElectionPool
from src.model_pool.contracts import SelectionRequest, SelectionResult
from src.storage import new_id

#: 案例办理先身份后结构两段完成各自义务，报告 Agent 一个会话完成叙事与报告
WorkPhase = Literal["identity", "structure", "report"]


@dataclass(frozen=True)
class CaseUnit:
    """诊断派发单元：案例身份取代 work 业务身份

    - 案例单元：case_id 是声明事件案例锚（与案例池稳定 id 同源），
      responsible_ids 是本次办理的声明
    - 报告单元：case_id 是 run 级报告锚，没有责任声明
    """

    case_id: str
    role: Literal["case", "report"]
    responsible_ids: tuple[str, ...]
    input_payload: dict[str, Any]


@dataclass
class DiagnosisWorkContext:
    """领域提供有权限的原工具与局部完成检查"""

    program: Any
    initial_messages: list[Any]
    completion_check: Callable[[], list[str]]


class DiagnosisWorkDomain(Protocol):
    """只暴露已接受候选和真实输入；调度侧不推断事件身份或补写报告"""

    def initial_work(self) -> list[CaseUnit]: ...

    def next_dispatch_attempt(self, case_id: str) -> int:
        """本轮派发的真实尝试序号（该案例既有执行事实数 + 1，跨轮累计）"""
        ...

    def build_context(
        self, unit: CaseUnit, phase: WorkPhase, observer: Any, corrections: dict[str, Any] | None
    ) -> DiagnosisWorkContext: ...

    def freeze_identity(self) -> None: ...

    def freeze_structure(self) -> None: ...

    def finishing_work(self) -> list[CaseUnit]: ...

    def publish(self) -> Any: ...


class DiagnosisWorkCorrections(ValueError):
    """屏障只退回具体冲突事实，由原责任案例以从零会话伸明修正"""

    def __init__(self, case_ids: tuple[str, ...], facts: dict[str, Any]) -> None:
        super().__init__("诊断候选存在需要原责任案例明确处置的冲突")
        self.case_ids, self.facts = case_ids, facts


@dataclass
class WorkProgress:
    """2026-10-15 用户裁定「删每回合消息级 checkpoint」：案例级累计回合与修正只存在内存

    会话不再持久化中途状态；案例失败即整轮失败，修正重派从零会话开始并沿用既有
    pending cases/retain 路径。回合预算保持旧累计语义：同一案例跨阶段与重派不刷新计数。
    执行身份按派发轮次铸造：同一轮内（identity/structure 两阶段与屏障修正重派）共用
    一行执行事实；新一轮（进程重启后的续跑）铸新身份并推进跨轮累计的真实尝试序号
    （dispatch_attempt），各轮终态互不覆盖；attempt_number 仍是本轮池内重试序号。
    """

    unit: CaseUnit
    execution_id: str
    rounds: int = 0
    attempt_number: int = 1
    dispatch_attempt: int = 1
    dispatched: bool = False
    physical_sequence: int = 0
    audit_sequence: int = 0
    corrections: dict[str, Any] | None = None


class DiagnosisWorkScheduler:
    """普通程序调度独立会话，屏障等待不占模型槽位且不新开逻辑执行

    2026-10-15 用户裁定「事件进案例池，按并发派agent处理，处理完为止」：事件 work 按
    模型池并发位（max_in_flight 既有容量选举）派发 agent 处理，事件全部完成后由一个
    收尾 agent 会话完成叙事组织与报告，随后 publish 落库。
    """

    def __init__(
        self,
        *,
        run_id: str,
        domain: DiagnosisWorkDomain,
        bus: EventBus,
        model_id: str,
        llm_factory: Callable[[str], Any],
        observer_factory: Callable[[WorkProgress], Any],
        audit_barrier: Callable[[], Any],
        is_cancelled: Callable[[], bool] | None = None,
        stream: Any = None,
        model_retries: int = 1,
    ) -> None:
        self.run_id, self.domain, self.bus = run_id, domain, bus
        self.llm_factory, self.observer_factory = llm_factory, observer_factory
        self.audit_barrier, self.is_cancelled, self.stream = audit_barrier, is_cancelled, stream
        self.model_retries = model_retries
        from src.config import settings

        # 本次运行继承诊断设置，跨阶段和重派使用累计计数，不因重新取得容量而刷新
        self.max_iterations = settings.models.diagnosis.max_iterations
        self.pool = ModelElectionPool(bus, run_id, max_attempts=1, fixed_model_id=model_id)
        self.progress: dict[str, WorkProgress] = {}
        self.completed: set[str] = set()
        self._waiting: dict[str, asyncio.Future[SelectionResult]] = {}

    def _state(self, unit: CaseUnit) -> WorkProgress:
        progress = self.progress.get(unit.case_id)
        if progress is None:
            # 执行身份与真实尝试序号按派发轮次铸造（executions 是每个真实 invocation
            # 的终态行，attempt 维度跨轮累计）：续跑重派必须以自己的身份与尝试序号
            # 收口，不能落到上一轮的终态行上。2026-10-17 run 52cbb1ac 实证：身份按
            # 案例一次定终身时，续跑的第一个案例收口就撞"execution 已结束，不能
            # 按不同结果重复收口"；尝试序号不跨轮累计则撞"该次尝试已有真实执行"。
            progress = WorkProgress(unit, new_id(), dispatch_attempt=self.domain.next_dispatch_attempt(unit.case_id))
            self.progress[unit.case_id] = progress
        return progress

    async def _assignments(self, queue: Any) -> None:
        while True:
            message = await queue.get()
            selected = message.payload
            if not isinstance(selected, SelectionResult) or selected.run_id != self.run_id:
                raise ValueError("诊断选举返回身份不一致")
            future = self._waiting.get(selected.work_id)
            if future is not None and future.cancelled():
                # 同批案例失败会取消仍在排队的兄弟，归还已经派发但尚未领取的容量
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
                    f"诊断容量派发没有可接收案例: case_id={selected.work_id} "
                    f"waiting={list(self._waiting)} future_done={future.done() if future else None}"
                )
            future.set_result(selected)

    async def _segment(self, unit: CaseUnit, phase: WorkPhase) -> None:
        progress = self._state(unit)
        if progress.rounds >= self.max_iterations:
            raise RuntimeError(f"budget_exhausted case_id={unit.case_id}")
        if self.is_cancelled is not None and self.is_cancelled():
            raise asyncio.CancelledError("诊断已取消")
        future: asyncio.Future[SelectionResult] = asyncio.get_running_loop().create_future()
        self._waiting[unit.case_id] = future
        await self.bus.request(
            Message(
                topic="pool.enqueue",
                source=f"queue:{self.run_id}",
                target=self.pool.address,
                run_id=self.run_id,
                work_id=unit.case_id,
                payload=SelectionRequest(
                    self.run_id, unit.case_id, resume_attempt=progress.attempt_number if progress.dispatched else None
                ),
            )
        )
        selected = await future
        self._waiting.pop(unit.case_id, None)
        progress.dispatched = True
        progress.attempt_number = selected.attempt_number
        observer = self.observer_factory(progress)
        release_capacity = False
        try:
            context = self.domain.build_context(unit, phase, observer, progress.corrections)
            llm = self.llm_factory(selected.model_id)
            work_stream = None
            if self.stream is not None:
                from src.agents.stream import AgentStream

                # 流作用域取实际阶段上下文：诊断阶段=阶段+案例角色（case/report），各案例
                # 的并行流由各自 stream_id 区分，作用域不再依赖 work 身份
                case_scope = unit.role

                async def emit(event: Any) -> None:
                    event.sub_stage, event.invocation_id = case_scope, progress.execution_id
                    event.stage = "diagnose"
                    await self.stream._emitter(event)

                work_stream = AgentStream(emit, sub_stage=case_scope, stream_id=progress.execution_id)
            progress.corrections = None
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
                agent=AgentAnnotation(role=unit.role),
                max_iterations=self.max_iterations,
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
                config={"recursion_limit": 4 * self.max_iterations + 10},
            )
            progress.rounds = int(final_state.get("iterations") or progress.rounds)
            progress.physical_sequence = int(getattr(observer, "_turn_counter", progress.physical_sequence))
            recorder = getattr(observer, "_recorder", None)
            progress.audit_sequence = int(getattr(recorder, "sequence", progress.audit_sequence))
            if final_state.get("halted"):
                raise RuntimeError(f"budget_exhausted case_id={unit.case_id}")
            if final_state.get("error"):
                raise RuntimeError(str(final_state["error"]))
            if not final_state.get("completion_ok"):
                raise RuntimeError(f"诊断案例未完成完整性检查: case_id={unit.case_id}")
            self.completed.add(unit.case_id)
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
            # 只有程序完整性检查通过后的会话结束归还容量；失败与取消由池退出一次性归还
            if release_capacity:
                await self.bus.request(
                    Message(
                        topic="pool.feedback",
                        source=f"queue:{self.run_id}",
                        target=self.pool.address,
                        run_id=self.run_id,
                        work_id=unit.case_id,
                        invocation_id=progress.execution_id,
                        payload={"reservation_id": selected.reservation_id, "outcome": "released"},
                    )
                )

    async def _wave(self, units: list[CaseUnit], phase: WorkPhase) -> None:
        for unit in units:
            self._state(unit)
        tasks = [asyncio.create_task(self._segment(unit, phase)) for unit in units]
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
        initial = self.domain.initial_work()
        if any(unit.role != "case" for unit in initial):
            raise ValueError("初始诊断案例只能是声明事件案例")
        # 2026-10-15 用户裁定：事件案例并发派发处理完为止；比较/结构/叙事独立 work 删除，
        # 案例自己在身份与结构两段完成义务，收尾 agent 一个会话完成叙事组织与报告
        await self._wave(initial, "identity")
        await self._freeze(self.domain.freeze_identity, "identity")
        await self._wave(initial, "structure")
        await self._freeze(self.domain.freeze_structure, "structure")
        finishing = self.domain.finishing_work()
        if len(finishing) != 1:
            raise ValueError("诊断收尾必须由一个报告agent完成")
        await self._wave(finishing, "report")
        return self.domain.publish()

    async def _freeze(self, freeze: Callable[[], None], phase: WorkPhase) -> None:
        while True:
            try:
                freeze()
                return
            except DiagnosisWorkCorrections as exc:
                if not exc.case_ids or set(exc.case_ids) - set(self.progress):
                    raise ValueError("屏障修正必须引用真实已派责任案例") from exc
                units = []
                for case_id in dict.fromkeys(exc.case_ids):
                    progress = self.progress[case_id]
                    if progress.rounds >= self.max_iterations:
                        raise RuntimeError(f"budget_exhausted case_id={case_id}") from exc
                    # 修正重派从零会话重新处理该案例，候选与冲突沿案例池既定路径
                    self.completed.discard(case_id)
                    progress.corrections = dict(exc.facts)
                    units.append(progress.unit)
                await self._wave(units, phase)
