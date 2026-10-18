"""每个角色 work 就是一个 agent，管理会话、程序、工具及自己的保存"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from functools import partial
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from src.agents.stream import AgentStream
from src.agents.turn_observer import AgentTurnObserver, build_invocation_context
from src.audit.module import AuditMessages
from src.case_pool import CasePool
from src.case_pool.contributions import CaseContribution
from src.event_bus import EventBus, Message
from src.event_trees.contributions import EventContribution
from src.event_trees.trees import CONTRIBUTION_KEYS, EventTrees
from src.fact_graph.contributions import FactContribution
from src.fact_graph.evidence import EvidenceParagraph
from src.fact_graph.graph import FactGraph
from src.utils.identity import stable_uuid
from src.work.annotation_work import WorkReceipt

from .agent_graph import build_agent_graph
from .agent_ir import AgentAnnotation
from .agent_runtime import AgentProgramRuntime
from .errors import AnnotationDependencyError, AnnotationInputError, AnnotationInvariantError
from .ledger import AnnotationToolLedger
from .paragraphs import build_chapter_paragraph_info
from .work_tools import build_work_tools


@dataclass
class WorkExecution:
    receipt: WorkReceipt
    invocation_id: str
    ledger: AnnotationToolLedger
    agent: AgentAnnotation
    task: asyncio.Task[Any] | None = None
    finished: bool = False
    end_requested: bool = False
    saved: bool = False
    fact_contribution: FactContribution | None = None
    event_contribution: EventContribution | None = None
    case_contribution: CaseContribution | None = None
    call_id: str = ""
    event_reads: dict[str, dict[str, Any]] = field(default_factory=dict)
    case_connections: list[str] = field(default_factory=list)
    case_reads: list[dict[str, Any]] = field(default_factory=list)
    case_save_warnings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def work_id(self) -> str:
        return self.receipt.work_id

    @property
    def contributions(self) -> dict[str, Any]:
        """保存确认只读取三个冻结快照，不保留第二份可变贡献真相"""
        if self.fact_contribution is None or self.event_contribution is None or self.case_contribution is None:
            raise ValueError("本 work 尚未冻结贡献")
        return {
            "facts": self.fact_contribution.snapshot(),
            "events": self.event_contribution.snapshot(),
            "cases": self.case_contribution.snapshot(),
        }

    def validate(self) -> list[str]:
        """返回当前 work 的完整性缺口；不改变写入状态，也不关闭写面"""
        missing: list[str] = []
        ledger = self.ledger
        if ledger.role in {"annotation", "metric"}:
            if ledger.metrics_payload is None:
                missing.append("metrics")
            pending = ledger.dialogue_ledger()["pending"]
            if pending:
                candidates = [
                    {
                        "candidate_index": index,
                        "candidate_key": item.candidate_key,
                        "content": item.content,
                        "start": item.start,
                        "end": item.end,
                    }
                    for index, item in enumerate(ledger.dialogue_candidates, 1)
                    if index in pending
                ]
                missing.append(f"dialogue_candidates={pending} details={candidates}")
        if ledger.pending_child_events:
            missing.append(f"pending_events={ledger.pending_child_events}")
        ledger._ensure_domain_payloads()
        try:
            ledger.validate_work_endpoints()
        except ValueError as exc:
            missing.append(f"endpoints={exc}")
        try:
            ledger._validate_domain_duplicates(ledger.domain_payloads)
        except ValueError as exc:
            missing.append(f"duplicates={exc}")
        return missing

    def output(self) -> dict[str, Any]:
        from .chapter_consolidation import RULE_VERSION

        ledger = self.ledger
        return {
            "contract_version": "event-tree-declarations-v1",
            "chapter_consolidation_version": RULE_VERSION,
            "declaration_contributions": {
                key: value
                for key, value in ledger.events.contribution_payloads().items()
                if key == "relations"
            },
            "metrics": ledger.metrics_payload.model_dump(mode="json") if ledger.metrics_payload else None,
            "events": [value.model_dump(mode="json") for value in ledger.bound_payloads.get("events", [])],
            "dialogues": [value.model_dump(mode="json") for value in ledger.bound_payloads.get("dialogues", [])],
            "character_observations": [
                value.model_dump(mode="json") for value in ledger.bound_payloads.get("character_observations", [])
            ],
            "paragraph_labels": [
                value.model_dump(mode="json") for value in ledger.bound_payloads.get("paragraph_labels", [])
            ],
            "coverage_warnings": ledger._paragraph_label_coverage_warnings(),
            "case_warnings": self.case_save_warnings,
        }


class AnnotationAgent:
    """同一 run 的 agent 持有同一图、树、案例实例，各 work 只有独立局部账本"""

    def __init__(
        self,
        bus: EventBus,
        run_id: str,
        session_factory: Callable[[], Session],
        *,
        novel_id: str,
        fact_graph: FactGraph | None = None,
        event_trees: EventTrees | None = None,
        case_pool: CasePool | None = None,
    ) -> None:
        self.bus, self.run_id, self.session_factory, self.novel_id = bus, run_id, session_factory, novel_id
        self.address = f"agent:{run_id}"
        # 三个域引擎由 agent 自建：编排层只派发 work，不持有事实图、事件树与案例池
        self.fact_graph = fact_graph if fact_graph is not None else FactGraph(run_scope=run_id)
        self.event_trees = event_trees if event_trees is not None else EventTrees(run_id)
        self.case_pool = case_pool if case_pool is not None else CasePool(run_id)
        self.lock = asyncio.Lock()
        self.executions: dict[str, WorkExecution] = {}
        for topic, handler in (
            ("agent.execute", self.execute),
            ("agent.save", self.save),
            ("agent.confirm", self.confirm),
            ("agent.saved_progress", self.saved_progress),
            ("agent.cancel", self.cancel),
            ("agent.abort", self.abort),
            ("agent.recover", self.recover),
            ("agent.consolidate_chapter", self.consolidate_chapter),
        ):
            bus.handle(topic, self.address, handler)

    async def consolidate_chapter(self, message: Message) -> dict[str, Any]:
        """编排只派发，章末三域操作和事务由 Agent 在共享锁内执行"""
        from .chapter_consolidation import consolidate_chapter

        async with self.lock:
            snapshot = self.case_pool.snapshot(f"chapter:{message.payload['chapter_id']}")
            executions = set(self.case_pool.executions)
            warnings = deepcopy(self.case_pool.save_warnings)
            try:

                def save() -> dict[str, Any]:
                    with self.session_factory() as session:
                        result = consolidate_chapter(
                            session,
                            self.run_id,
                            message.payload["chapter_id"],
                            self.case_pool,
                            recheck=bool(message.payload.get("recheck", False)),
                        )
                        session.commit()
                        return result

                # 取消协程不能让后台事务继续写、前台却提前回滚内存并释放共享锁
                transaction = asyncio.create_task(asyncio.to_thread(save))
                cancelled = False
                try:
                    result = await asyncio.shield(transaction)
                except asyncio.CancelledError:
                    cancelled = True
                    result = await transaction
            except BaseException:
                self.case_pool.restore(snapshot)
                self.case_pool.executions = executions
                self.case_pool.save_warnings = warnings
                raise
            if result["status"] == "saved":
                self.case_pool.confirm_pending(result["author"])
            if cancelled:
                raise asyncio.CancelledError
            return result

    async def execute(self, message: Message) -> dict[str, Any]:
        from src.agents.annotation.queries import DatabaseAnnotationQueryService
        from src.config import settings
        from src.embedding import EmbeddingClient
        from src.model_pool.configuration import load_task_config
        from src.model_pool.llm import build_chat_model

        receipt = message.payload
        invocation_id = uuid4().hex
        payload = receipt.payload
        paragraph_info = build_chapter_paragraph_info(payload["paragraphs"])
        embedding = EmbeddingClient(novel_id=self.novel_id)
        query = DatabaseAnnotationQueryService(
            self.session_factory,
            run_id=self.run_id,
            current_chapter_id=payload["chapter_id"],
            current_first_paragraph_id=min(paragraph_info.paragraph_ids),
            current_last_paragraph_id=max(paragraph_info.paragraph_ids),
            embedding_client=embedding,
        )
        if not str(payload["chapter_text"]).strip():
            # 章文本非空是标注 work 的前置事实（诊断会话复用账本后才允许空），这里只拦标注面
            raise AnnotationInputError("标注 work 的章正文不能为空")
        ledger = AnnotationToolLedger(
            run_scope=self.run_id,
            current_chapter_id=payload["chapter_id"],
            current_chapter_text=payload["chapter_text"],
            allow_future_context=settings.models.annotation.allow_future_context,
            graph=self.fact_graph,
            paragraph_info=paragraph_info,
            current_chapter_order=payload["chapter_sequence"],
            work_id=receipt.work_id,
            invocation_id=invocation_id,
            role=payload["role"],
        )
        execution = WorkExecution(
            receipt, invocation_id, ledger, AgentAnnotation(role=payload["role"]), task=asyncio.current_task()
        )
        self.executions[receipt.work_id] = execution
        await self.bus.request(
            Message(
                topic="queue.started",
                source=self.address,
                target=f"queue:{self.run_id}",
                run_id=self.run_id,
                work_id=receipt.work_id,
                invocation_id=invocation_id,
            )
        )
        author = invocation_id
        async with self.lock:
            self.fact_graph.begin(author, payload["chapter_sequence"], payload["role"])
            self.event_trees.begin(author)
            self.case_pool.begin(author)
        recorder = AuditMessages(self.bus, self.run_id, receipt.work_id, invocation_id, payload["role"])
        audit_id: int | None = None
        try:
            model = build_chat_model("annotation", config=load_task_config("annotation", model_id=payload["model_id"]))

            model_name = str(getattr(model, "model_name", None) or getattr(model, "model", "unknown"))
            audit_context = build_invocation_context(
                run_id=self.run_id,
                task_type="annotation",
                execution_id=invocation_id,
                attempt_number=payload["attempt_number"],
                model=model_name,
                chapter_id=payload["chapter_id"],
                role=payload["role"],
            )
            audit_id = recorder.start_invocation(**audit_context)
            observer = AgentTurnObserver(recorder, invocation_id=audit_id, context=audit_context)
            stream_sequence = 0

            async def emit(event: Any) -> None:
                nonlocal stream_sequence
                stream_sequence += 1
                await self.bus.request(
                    Message(
                        topic="sse.show",
                        source=self.address,
                        target=f"sse:{self.run_id}",
                        run_id=self.run_id,
                        work_id=receipt.work_id,
                        invocation_id=invocation_id,
                        message_id=f"{invocation_id}:sse:{stream_sequence}",
                        payload=event,
                    )
                )

            from src.sse.events import StreamEvent

            await emit(
                StreamEvent(
                    action="work_reset", stage="annotate", sub_stage=payload["role"], chapter_id=payload["chapter_id"]
                )
            )
            stream = AgentStream(
                emit, chapter_id=payload["chapter_id"], sub_stage=payload["role"], stream_id=invocation_id
            )
            ledger.invoke_tool = partial(self.invoke_tool, execution)
            ledger.finish_work = execution.validate
            tools = build_work_tools(self, execution, query)
            runtime = AgentProgramRuntime(
                {tool.name: tool for tool in tools}, ledger, execution.agent, observer=observer, stream=stream
            )
            program = runtime.build_tool()
            from loguru import logger

            from src.config.settings_service import iteration_budget_info

            max_iterations, budget_source = iteration_budget_info("annotation")
            logger.info(
                "annotation budget work_id={} invocation_id={} max_iterations={} source={}",
                execution.work_id,
                invocation_id,
                max_iterations,
                budget_source,
            )

            def completion_check() -> list[str]:
                missing = execution.validate()
                if not missing:
                    execution.finished = True
                    execution.agent.finished = True
                    ledger.chapter_finished = True
                return missing

            graph = build_agent_graph(
                model,
                program,
                runtime.finish_tool,
                ledger=ledger,
                agent=execution.agent,
                max_iterations=max_iterations,
                stream=stream,
                observer=observer,
                retries=settings.models.annotation.total_attempts,
                completion_check=completion_check,
            )
            from .prompts import AGENT_ROLE_SCOPES, AGENT_SYSTEM_PROMPT, build_agent_message

            scope = AGENT_ROLE_SCOPES.get(payload["role"], "独立完成本章实体关系、事件参与者、全部对话候选和指标")
            try:
                state = await graph.ainvoke(
                    {
                        "messages": [
                            SystemMessage(
                                content=AGENT_SYSTEM_PROMPT + "\n全书图树案例共享；finish 只完成自己的标注。"
                                "push_case(case_type,description) 归入人物/关系/对话/事件，"
                                "promise_case 只填真实 case_id。"
                                "跨章连接用 write_link 引用已实际读取且已保存的声明；未保存端点不能连接。"
                            ),
                            HumanMessage(
                                content=build_agent_message(
                                    role=payload["role"],
                                    paragraph_info=paragraph_info,
                                    candidates=ledger.dialogue_candidates,
                                    role_scope=scope,
                                    chapter_id=payload["chapter_id"],
                                    chapter_order=ledger.current_chapter_order,
                                )
                            ),
                        ],
                        "phase": "chapter_open",
                        "iterations": 0,
                        "error": None,
                    },
                    config={"recursion_limit": 4 * max_iterations + 10},
                )
            except AnnotationDependencyError:
                # 外部依赖失败不得进入文本模型的瞬态重派通道
                raise
            except Exception as exc:
                from src.agents.stream import _is_transient_model_error

                from .errors import AnnotationRetryableError

                if _is_transient_model_error(exc):
                    raise AnnotationRetryableError(f"当前模型请求重试耗尽: {exc}") from exc
                raise
            if state.get("error"):
                from .errors import AnnotationInvariantError

                raise AnnotationInvariantError(str(state["error"]))
            if not execution.finished:
                failed = [
                    {key: op.get(key) for key in ("tool_name", "message", "error_code")}
                    for op in runtime.ops
                    if op.get("status") != "success"
                ]
                from .errors import AnnotationBudgetExhaustedError

                raise AnnotationBudgetExhaustedError(
                    f"budget_exhausted work_id={receipt.work_id} invocation_id={invocation_id} "
                    f"iterations_used={state.get('iterations', 0)} "
                    f"iterations_limit={max_iterations} "
                    f"end_signal={state.get('end_signal', 'none')} missing={execution.validate()} "
                    f"error={state.get('error')} failed_calls={failed}"
                )
            async with self.lock:
                self.freeze(execution)
            recorder.finish_invocation(**audit_context, status="success")
            await self.bus.request(
                Message(
                    topic="audit.barrier",
                    source=self.address,
                    target=f"audit:{self.run_id}",
                    run_id=self.run_id,
                    work_id=receipt.work_id,
                    invocation_id=invocation_id,
                )
            )
            return {"outcome": "completed", "invocation_id": invocation_id}
        except BaseException as exc:
            from loguru import logger

            logger.error("work 执行失败 work_id={} role={} error={!r}", receipt.work_id, payload["role"], exc)
            async with self.lock:
                self.fact_graph.rollback(author)
                self.event_trees.rollback(author)
                self.case_pool.rollback(author)
            if audit_id is not None:
                recorder.finish_invocation(**audit_context, status="error", final_error=str(exc))
            await self.bus.request(
                Message(
                    topic="audit.barrier",
                    source=self.address,
                    target=f"audit:{self.run_id}",
                    run_id=self.run_id,
                    work_id=execution.work_id,
                    invocation_id=execution.invocation_id,
                )
            )
            if isinstance(exc, asyncio.CancelledError):
                raise

            from .errors import AnnotationBudgetExhaustedError, AnnotationRetryableError

            if isinstance(exc, AnnotationBudgetExhaustedError):
                return {"outcome": "budget_exhausted", "invocation_id": invocation_id, "error": str(exc)}

            if not isinstance(exc, AnnotationRetryableError):
                raise
            return {"outcome": "retry", "invocation_id": invocation_id, "error": str(exc)}

    async def invoke_tool(self, execution: WorkExecution, tools: dict[str, Any], call: dict[str, Any]) -> str:
        """工具内存事务中无模型、原文 I/O、总线或数据库等待"""
        tool = tools[call["name"]]
        if execution.finished:
            raise ValueError(f"work_id={execution.work_id} 已 finish，拒绝迟到调用={call['name']}")
        if call["name"] == "execute_code":
            return str(await tool.ainvoke(call.get("args", {})))
        if call["name"] in {"read_text", "search_text", "read_chapter_text", "anchor_record"}:
            # 原文 I/O 不持书级锁，结束后仅在锁内登记可选案例关联
            args = dict(call.get("args", {}))
            caseid = args.pop("caseid", None)
            result = await tool.ainvoke(args)
            if caseid is not None:
                from src.case_pool.tool_binding import attach_case_link

                async with self.lock:
                    result = attach_case_link(
                        result,
                        caseid,
                        lambda **values: self.case_pool.associate(
                            values["caseid"],
                            execution.invocation_id,
                            tool_name=call["name"],
                            call_id=str(call["id"]),
                            receipt=values["receipt"],
                            is_write=False,
                        ),
                        call["name"],
                    )
            execution.case_reads.append({"tool": call["name"], "result": str(result)})
            return str(result)
        async with self.lock:
            author = execution.invocation_id
            execution.call_id = str(call["id"])
            with self.fact_graph.author(author):
                snapshots = (
                    execution.ledger.snapshot(),
                    self.fact_graph.snapshot(),
                    self.event_trees.snapshot(author),
                    self.case_pool.snapshot(author),
                )
                local = deepcopy((execution.event_reads, execution.case_connections, execution.case_reads))
                finished = execution.finished
                try:
                    args = tool.args_schema.model_validate(call.get("args", {})).model_dump(exclude_unset=True)
                    execution.ledger.confirmed_declaration_ids = self.event_trees.confirmed_declaration_ids()
                    result = tool.func(**args)
                    self.event_trees.sync(
                        author, execution.ledger.current_chapter_id, execution.ledger.bound_payloads.get("events", [])
                    )
                    self.event_trees.sync_contributions(author, execution.ledger.events.contribution_payloads())
                    return str(result)
                except BaseException:
                    execution.ledger.restore(snapshots[0])
                    self.fact_graph.restore(snapshots[1])
                    self.event_trees.restore(snapshots[2])
                    self.case_pool.restore(snapshots[3])
                    # 就地恢复：读取工具装配时捕获的是这三个容器对象本身，
                    # 换成快照副本会让此后读取的记录与工具持有的容器断裂
                    execution.event_reads.clear()
                    execution.event_reads.update(local[0])
                    execution.case_connections[:] = local[1]
                    execution.case_reads[:] = local[2]
                    execution.finished = finished
                    raise

    def _execution(self, message: Message) -> WorkExecution:
        execution = self.executions[message.work_id]
        if execution.invocation_id != message.invocation_id:
            raise ValueError(f"迟到消息 work_id={message.work_id} invocation_id={message.invocation_id}")
        return execution

    async def save(self, message: Message) -> str:
        execution = self._execution(message)
        return await asyncio.to_thread(self._save, execution, message.payload)

    def _save(self, execution: WorkExecution, session: Session) -> str:
        from src.storage.models import ChapterAnnotation

        from .chapter_consolidation import RULE_VERSION

        if not execution.finished:
            raise ValueError("只有通过程序完整性检查的 work 可以保存")
        payload = execution.receipt.payload
        annotation_id = stable_uuid(self.run_id, execution.work_id)
        existing = session.get(ChapterAnnotation, annotation_id)
        if existing is not None:
            if existing.execution_id != execution.invocation_id:
                raise ValueError(f"chapter={payload['chapter_id']} role={payload['role']} 已有另一份不可变结果")
            return annotation_id
        output = execution.output()
        metrics = output["metrics"]
        session.add(
            ChapterAnnotation(
                record_id=annotation_id,
                execution_id=execution.invocation_id,
                run_id=self.run_id,
                chapter_id=int(payload["chapter_id"]),
                role=str(payload["role"]),
                # 记录合同版本取本次产出的内容合同：事件域读写按该值判定记录形状
                contract_version=str(output["contract_version"]),
                chapter_consolidation_version=RULE_VERSION,
                summary=metrics["summary"] if metrics else None,
                emotional_valence=metrics["emotional_valence"] if metrics else None,
                narrative_function=metrics["narrative_function"] if metrics else None,
                pivot_moment=metrics["pivot_moment"] if metrics else None,
                cliffhanger=metrics["cliffhanger"] if metrics else None,
            )
        )
        session.flush()
        assert execution.event_contribution is not None
        assert execution.fact_contribution is not None
        assert execution.case_contribution is not None
        # 实体身份行先落：事件参与者与关系事实都按同一批确定性身份建外键
        self.fact_graph.ensure_entity_rows(session, execution.fact_contribution)
        self.event_trees.save_work(session, execution.event_contribution, annotation_id)
        self.fact_graph.save_work(session, execution.fact_contribution, annotation_id)
        self._save_dialogues(session, execution)
        self._save_paragraph_labels(session, execution, annotation_id)
        execution.case_save_warnings = self.case_pool.save_work(session, execution.case_contribution)
        saved = session.get(ChapterAnnotation, annotation_id)
        if saved is None:
            raise AnnotationInvariantError("标注正式产物写入后不可读取")
        session.flush()
        return annotation_id

    def _save_paragraph_labels(self, session: Session, execution: WorkExecution, annotation_id: str) -> None:
        """逐段情绪标签随正式记录落入分析条目；段号是章内映射后的全局 paragraph_id"""
        from src.storage.models import AnalysisAssessment

        for label in execution.output()["paragraph_labels"]:
            session.add(
                AnalysisAssessment(
                    assessment_id=stable_uuid(
                        self.run_id, annotation_id, "paragraph_emotion", str(label["paragraph_id"])
                    ),
                    record_id=annotation_id,
                    paragraph_id=int(label["paragraph_id"]),
                    emotion=int(label["emotion"]),
                )
            )
        session.flush()

    async def confirm(self, message: Message) -> None:
        execution = self._execution(message)
        async with self.lock:
            self.fact_graph.confirm(execution.invocation_id)
            self.event_trees.confirm(execution.invocation_id)
            self.case_pool.confirm(execution.invocation_id)
            execution.saved = True

    async def saved_progress(self, message: Message) -> None:
        """队列交付已确认章进度，由 Agent 向展示模块发送自身工作事实"""
        from src.sse.events import StreamEvent

        execution = self._execution(message)
        if not execution.saved:
            raise ValueError(f"work_id={execution.work_id} 尚未确认保存，不能展示保存进度")
        payload, progress = execution.receipt.payload, message.payload
        current, total = progress["current"], progress["total"]
        for event in (
            StreamEvent(
                action="work_saved", stage="annotate", sub_stage=payload["role"], chapter_id=payload["chapter_id"]
            ),
            StreamEvent(
                action="progress",
                stage="annotate",
                sub_stage=payload["role"],
                chapter_id=payload["chapter_id"],
                current=current,
                total=total,
                percent=progress["percent"],
                sub_percent=progress["sub_percent"],
                message=f"{payload['chapter_label']} {payload['role']} 已保存",
            ),
        ):
            await self.bus.request(
                Message(
                    topic="sse.show",
                    source=self.address,
                    target=f"sse:{self.run_id}",
                    run_id=self.run_id,
                    work_id=execution.work_id,
                    invocation_id=execution.invocation_id,
                    message_id=f"{execution.invocation_id}:sse:saved:{event.action}",
                    payload=event,
                )
            )

    async def abort(self, message: Message) -> None:
        """队列已核实未保存后撤销本执行，不能由取消消息猜测提交结果"""
        execution = self._execution(message)
        async with self.lock:
            if execution.saved:
                raise ValueError(f"work_id={execution.work_id} 已确认保存，不能撤销")
            self.fact_graph.rollback(execution.invocation_id)
            self.event_trees.rollback(execution.invocation_id)
            self.case_pool.rollback(execution.invocation_id)

    def freeze(self, execution: WorkExecution) -> None:
        """程序完整性检查通过后固定贡献，数据库线程不遍历并发修改的全书字典"""
        author = execution.invocation_id
        facts: dict[str, Any] = self.fact_graph.drain_ops(author)
        keys = {self.fact_graph.entity_key(op["name"], op["entity_type"]) for op in facts["entity_ops"]}
        for op in facts["relation_assert_ops"]:
            keys.update((str(op["from_entity"]), str(op["to_entity"])))
        output = execution.output()
        keys.update(
            self.fact_graph.entity_key(item["character"], "character") for item in output["character_observations"]
        )
        keys.update(
            self.fact_graph.entity_key(item["speaker"], "character") for item in output["dialogues"] if item["speaker"]
        )
        for event in output["events"]:
            keys.update(str(item["entity"]) for item in event["participants"])
        facts["entities"] = {
            self.fact_graph.entity_id_for_key(key): {
                "entity_id": self.fact_graph.entity_id_for_key(key),
                "name": self.fact_graph.display_name(key),
                "entity_type": str(self.fact_graph.entity_type_by_key(key)),
            }
            for key in keys
        }
        self.fact_graph.reference_entities(author, list(facts["entities"].values()))
        contributions = {
            "facts": facts,
            "events": {
                **{
                    key: deepcopy(
                        {
                            identifier: value
                            for identifier, value in getattr(self.event_trees, key).items()
                            if value["author"] == author
                        }
                    )
                    for key in CONTRIBUTION_KEYS
                },
                "process_evidence": {
                    identifier: [
                        ref.model_dump(mode="json") for ref in execution.ledger.source_anchors[f"{tree_key}/{node_key}"]
                    ]
                    for tree_key, tree_id in execution.ledger.tree_key_index.items()
                    for node_key, identifier in execution.ledger.event_trees[tree_id]["nodes"].items()
                    if f"{tree_key}/{node_key}" in execution.ledger.source_anchors
                },
                "source_anchors": {
                    key: [ref.model_dump(mode="json") for ref in values]
                    for key, values in execution.ledger.source_anchors.items()
                },
                "actions": self.event_trees.freeze_actions(author, execution.receipt.payload["paragraphs"]),
                "nodes": deepcopy(
                    {key: value for key, value in self.event_trees.nodes.items() if value["author"] == author}
                ),
                "connections": deepcopy(
                    {key: value for key, value in self.event_trees.connections.items() if value["author"] == author}
                ),
            },
            "cases": {
                "created_case_ids": sorted(self.case_pool.created.get(author, set())),
                "registrations": deepcopy(
                    {
                        identifier: self.case_pool.cases[identifier]
                        for identifier in self.case_pool.registrations.get(author, set())
                    }
                ),
                "deliveries": deepcopy(self.case_pool.deliveries.get(author, [])),
            },
        }

        payload = execution.receipt.payload
        paragraphs = tuple(
            EvidenceParagraph(row.chapter_id, row.paragraph_id, row.text, row.local_start_char, row.local_end_char)
            for row in payload["paragraphs"]
        )
        execution.fact_contribution = FactContribution(
            self.run_id,
            execution.invocation_id,
            payload["chapter_id"],
            paragraphs,
            json.dumps(facts, ensure_ascii=False),
            json.dumps(output["character_observations"], ensure_ascii=False),
        )
        execution.event_contribution = EventContribution(
            self.run_id,
            execution.invocation_id,
            payload["chapter_sequence"],
            paragraphs,
            json.dumps(contributions["events"], ensure_ascii=False),
            json.dumps(facts["entities"], ensure_ascii=False),
        )
        execution.case_contribution = CaseContribution(
            self.run_id,
            execution.invocation_id,
            json.dumps(contributions["cases"], ensure_ascii=False),
        )

    def _save_dialogues(self, session: Session, execution: WorkExecution) -> None:
        from src.fact_graph.graph import mention_uuid
        from src.storage.models import DialogueRecord

        if execution.ledger.role not in {"annotation", "metric"}:
            return
        for content in execution.output()["dialogues"]:
            identifier = stable_uuid(self.run_id, execution.work_id, content["candidate_key"])
            session.add(
                DialogueRecord(
                    dialogue_id=identifier,
                    run_id=self.run_id,
                    chapter_id=execution.ledger.current_chapter_id,
                    creation_execution_id=execution.invocation_id,
                    candidate_key=content["candidate_key"],
                    start_char=int(content["start"]),
                    end_char=int(content["end"]),
                    speaker_entity_id=mention_uuid(
                        self.run_id, execution.ledger.current_chapter_id, content["speaker"], "character"
                    )
                    if content["speaker"]
                    else None,
                    tone=content["tone"],
                    is_inner_monologue=bool(content["is_inner_monologue"]),
                )
            )
        session.flush()

    async def cancel(self, message: Message) -> None:
        execution = self.executions.get(message.work_id)
        # finish 只结束模型写面，尚在等执行回执的成功 work 仍属于保存前取消范围
        if execution is not None and not execution.saved and execution.task is not None:
            execution.task.cancel()

    async def recover(self, message: Message) -> None:
        """业务恢复由 agent 发起，域各自恢复贡献，历史审计不成为读取授权"""
        if message.payload.get("mode") == "chapter_reset":
            from src.sse.events import StreamEvent

            for chapter_id in message.payload["chapter_ids"]:
                await self.bus.request(
                    Message(
                        topic="sse.show",
                        source=self.address,
                        target=f"sse:{self.run_id}",
                        run_id=self.run_id,
                        message_id=f"{message.message_id}:chapter:{chapter_id}",
                        payload=StreamEvent(action="chapter_reset", stage="annotate", chapter_id=chapter_id),
                    )
                )
            return
        if message.payload.get("mode") == "saved_work":
            await self._recover_saved_work(message)
            return
        await asyncio.to_thread(self._recover, message.payload)

    async def _recover_saved_work(self, message: Message) -> None:
        """确认故障只重建当前已保存作者，不清理其他 work 或释放其案例占用"""
        execution = self._execution(message)

        def load() -> tuple[Any, Any, Any]:
            with self.session_factory() as session:
                args = (
                    session,
                    execution.invocation_id,
                    stable_uuid(self.run_id, execution.work_id),
                )
                return (
                    self.fact_graph.load_saved_work(*args),
                    self.event_trees.load_saved_work(*args),
                    self.case_pool.load_saved_work(*args),
                )

        snapshots = await asyncio.to_thread(load)
        async with self.lock:
            self.fact_graph.recover_work(snapshots[0])
            self.event_trees.recover_work(snapshots[1])
            self.case_pool.recover_work(snapshots[2])
            execution.saved = False

    def _recover(self, data: dict[str, Any]) -> None:
        """整章废弃按产物行与执行归属清理：产物、域事实与真实尝试一起退场"""
        from sqlalchemy import delete, select

        from src.storage.models import (
            BookCase,
            Chapter,
            ChapterAnnotation,
            DialogueRecord,
            EventDeclaration,
            Execution,
        )

        session = data["session"]
        chapter_ids = {int(chapter) for chapter in data["chapter_ids"]}
        ordered_chapters = sorted(chapter_ids)
        executions = select(Execution.execution_id).where(
            Execution.run_id == self.run_id, Execution.chapter_id.in_(ordered_chapters)
        )
        discarded_records = select(ChapterAnnotation.record_id).where(
            ChapterAnnotation.run_id == self.run_id, ChapterAnnotation.chapter_id.in_(ordered_chapters)
        )
        discarded_declarations = select(EventDeclaration.declaration_id).where(
            EventDeclaration.record_id.in_(discarded_records)
        )
        discarded_dialogues = select(DialogueRecord.dialogue_id).where(
            DialogueRecord.creation_execution_id.in_(executions)
        )
        # 案例的正式目标（声明/对话）随整章废弃退场：先在目标外键（RESTRICT）之前清案例行
        session.execute(
            delete(BookCase).where(
                BookCase.automatic_declaration_id.in_(discarded_declarations)
                | BookCase.declaration_target_id.in_(discarded_declarations)
                | BookCase.dialogue_target_id.in_(discarded_dialogues)
            )
        )
        # 本章章末核对凭据的来源集合已失效：撤销凭据，重建不受旧回执阻挡
        from src.agents.annotation.chapter_consolidation import discard_chapter_receipts

        discard_chapter_receipts(session, self.run_id, chapter_ids)
        execution_ids = set(session.scalars(executions))
        self.fact_graph.discard_storage(session, execution_ids)
        self.event_trees.discard_storage(session, execution_ids)
        session.execute(delete(DialogueRecord).where(DialogueRecord.creation_execution_id.in_(executions)))
        session.execute(delete(ChapterAnnotation).where(ChapterAnnotation.record_id.in_(discarded_records)))
        session.flush()
        records = list(
            session.execute(
                select(
                    ChapterAnnotation.record_id,
                    ChapterAnnotation.execution_id,
                    ChapterAnnotation.role,
                    ChapterAnnotation.chapter_id,
                    Chapter.sequence,
                )
                .join(
                    Chapter,
                    (Chapter.run_id == ChapterAnnotation.run_id)
                    & (Chapter.chapter_id == ChapterAnnotation.chapter_id),
                )
                .where(ChapterAnnotation.run_id == self.run_id)
            )
        )
        self.fact_graph.rebuild_storage(session)
        self.event_trees.rebuild_storage(session)
        self.fact_graph.restore_storage(session, records)
        self.event_trees.restore_storage(session, records)
        self.case_pool.restore_storage(session, execution_ids)
        # 产物、域事实与案例支持都已退场，正式尝试行随整章废弃退出（模型调用行由外键级联）
        session.execute(
            delete(Execution).where(Execution.run_id == self.run_id, Execution.chapter_id.in_(ordered_chapters))
        )
        session.flush()

    def close(self) -> None:
        for topic in (
            "agent.execute",
            "agent.save",
            "agent.confirm",
            "agent.saved_progress",
            "agent.cancel",
            "agent.abort",
            "agent.recover",
            "agent.consolidate_chapter",
        ):
            self.bus.unhandle(topic, self.address)
