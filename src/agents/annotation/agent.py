"""每个角色 work 就是一个 agent，管理会话、程序、工具及自己的保存"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from functools import partial
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from src.agents.annotation.work import WorkReceipt
from src.agents.audit.module import AuditMessages
from src.agents.audit.observer import AgentTurnObserver, build_invocation_context
from src.agents.stream import AgentStream
from src.case_pool import CasePool
from src.event_bus import EventBus, Message
from src.event_trees.submission import build_event_submission_tool
from src.event_trees.trees import EventTrees
from src.fact_graph.graph import FactGraph
from src.storage.models import AnalysisOutput

from .identity import stable_uuid
from .ledger import AnnotationToolLedger
from .paragraphs import build_chapter_paragraph_info
from .subagent_graph import build_subagent_graph
from .subagent_ir import SubagentAnnotation
from .subagent_runtime import SubagentProgramRuntime
from .work_tools import build_work_tools


def _model_provider(model: Any) -> str:
    """模型地址决定审计来源，与工作执行协议无关"""
    base_url = str(getattr(model, "base_url", "") or getattr(model, "openai_api_base", "") or "")
    return "cloud" if base_url and "localhost" not in base_url and "127.0.0.1" not in base_url else "local"


@dataclass
class WorkExecution:
    receipt: WorkReceipt
    invocation_id: str
    ledger: AnnotationToolLedger
    subagent: SubagentAnnotation
    task: asyncio.Task[Any] | None = None
    finished: bool = False
    saved: bool = False
    contributions: dict[str, Any] = field(default_factory=dict)
    call_id: str = ""
    event_reads: dict[str, dict[str, Any]] = field(default_factory=dict)
    case_connections: list[str] = field(default_factory=list)
    case_reads: list[dict[str, Any]] = field(default_factory=list)

    @property
    def work_id(self) -> str:
        return self.receipt.work_id

    def validate(self) -> None:
        """只检查自身角色，候选必须真实逐条判定，绝不填中性指标"""
        ledger = self.ledger
        ledger._reconcile_pending_children()
        if ledger.role in {"solo", "evidence"}:
            if ledger.metrics_payload is None:
                raise ValueError(f"finish role={ledger.role} metrics=None，先提交本 work 指标")
            pending = ledger.dialogue_ledger()["pending"]
            if pending:
                raise ValueError(f"finish role={ledger.role} 未判候选={pending}，先逐条判定")
        if ledger.pending_child_events:
            raise ValueError(f"finish 挂起节点={ledger.pending_child_events}，先完成节点结构")
        ledger._ensure_domain_payloads()
        ledger.validate_work_endpoints()
        ledger._validate_domain_duplicates(ledger.domain_payloads)

    def output(self) -> dict[str, Any]:
        ledger = self.ledger
        return {
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
        fact_graph: FactGraph,
        event_trees: EventTrees,
        case_pool: CasePool,
    ) -> None:
        self.bus, self.run_id, self.session_factory, self.novel_id = bus, run_id, session_factory, novel_id
        self.address = f"agent:{run_id}"
        self.fact_graph, self.event_trees, self.case_pool = fact_graph, event_trees, case_pool
        self.lock = asyncio.Lock()
        self.executions: dict[str, WorkExecution] = {}
        for topic, handler in (
            ("agent.execute", self.execute),
            ("agent.save", self.save),
            ("agent.confirm", self.confirm),
            ("agent.saved_progress", self.saved_progress),
            ("agent.cancel", self.cancel),
            ("agent.abort", self.abort),
            ("agent.check", self.check),
            ("agent.recover", self.recover),
        ):
            bus.handle(topic, self.address, handler)

    async def execute(self, message: Message) -> dict[str, Any]:
        from src.config import settings
        from src.config.input_config import load_task_config
        from src.embedding import EmbeddingClient
        from src.model_pool.llm import build_chat_model
        from src.storage.repositories import DatabaseAnnotationQueryService

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
            receipt, invocation_id, ledger, SubagentAnnotation(role=payload["role"]), task=asyncio.current_task()
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
        author = (receipt.work_id, invocation_id)
        async with self.lock:
            self.fact_graph.begin(*author, payload["chapter_sequence"], payload["role"])
            self.event_trees.begin(*author)
            self.case_pool.begin(*author)
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
                model_provider=_model_provider(model),
                chapter_id=payload["chapter_id"],
                work_id=receipt.work_id,
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
            runtime = SubagentProgramRuntime(
                {tool.name: tool for tool in tools}, ledger, execution.subagent, observer=observer, stream=stream
            )
            program = runtime.build_tool()
            graph = build_subagent_graph(
                model,
                program,
                runtime.finish_tool,
                ledger=ledger,
                subagent=execution.subagent,
                max_iterations=settings.models.annotation.max_iterations,
                stream=stream,
                observer=observer,
                retries=settings.models.annotation.total_attempts,
                event_submission_tool=build_event_submission_tool(runtime),
            )
            from .prompts import SUBAGENT_ROLE_SCOPES, SUBAGENT_SYSTEM_PROMPT, build_subagent_message

            scope = SUBAGENT_ROLE_SCOPES.get(payload["role"], "独立完成本章实体关系、事件参与者、全部对话候选和指标")
            try:
                state = await graph.ainvoke(
                    {
                        "messages": [
                            SystemMessage(
                                content=SUBAGENT_SYSTEM_PROMPT + "\n全书图树案例共享；finish 只完成自己的 work。"
                                "push_case 只填 description，promise_case 只填真实 case_id。"
                                "跨章 event 明确填已读取的 parent_ref/node_ref；未保存端点不能连接。"
                            ),
                            HumanMessage(
                                content=build_subagent_message(
                                    role=payload["role"],
                                    paragraph_info=paragraph_info,
                                    candidates=ledger.dialogue_candidates,
                                    role_scope=scope,
                                )
                            ),
                        ],
                        "phase": "chapter_open",
                        "iterations": 0,
                        "error": None,
                    }
                )
            except Exception as exc:
                from src.agents.stream import _is_transient_model_error

                from .errors import AnnotationRetryableError

                if _is_transient_model_error(exc):
                    raise AnnotationRetryableError(f"当前模型请求重试耗尽: {exc}") from exc
                raise
            if state.get("error") or not execution.finished:
                failed = [
                    {key: op.get(key) for key in ("tool_name", "message", "error_code")}
                    for op in runtime.ops
                    if op.get("status") != "success"
                ]
                from .errors import AnnotationRetryableError

                raise AnnotationRetryableError(
                    state.get("error") or f"当前角色未通过显式 finish，不能保存；失败调用={failed}"
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
                self.fact_graph.rollback(*author)
                self.event_trees.rollback(*author)
                self.case_pool.rollback(*author)
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

            from .errors import AnnotationRetryableError

            if not isinstance(exc, AnnotationRetryableError):
                raise
            return {"outcome": "retry", "invocation_id": invocation_id, "error": str(exc)}

    async def invoke_tool(self, execution: WorkExecution, tools: dict[str, Any], call: dict[str, Any]) -> str:
        """工具内存事务中无模型、原文 I/O、总线或数据库等待"""
        tool = tools[call["name"]]
        if execution.finished:
            raise ValueError(f"work_id={execution.work_id} 已 finish，拒绝迟到调用={call['name']}")
        if call["name"] in {"execute_code", "submit_events"}:
            return str(await tool.ainvoke(call.get("args", {})))
        if call["name"] in {"read_text", "search_text", "read_chapter_text", "anchor_record"}:
            result = await tool.ainvoke(call.get("args", {}))
            execution.case_reads.append({"tool": call["name"], "result": str(result)})
            return str(result)
        async with self.lock:
            author = (execution.work_id, execution.invocation_id)
            execution.call_id = str(call["id"])
            with self.fact_graph.author(*author):
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
                    result = tool.func(**args)
                    self.event_trees.sync(
                        author, execution.ledger.current_chapter_id, execution.ledger.bound_payloads.get("events", [])
                    )
                    return str(result)
                except BaseException:
                    execution.ledger.restore(snapshots[0])
                    self.fact_graph.restore(snapshots[1])
                    self.event_trees.restore(snapshots[2])
                    self.case_pool.restore(snapshots[3])
                    execution.event_reads, execution.case_connections, execution.case_reads = local
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

    @staticmethod
    def actual_input(execution: WorkExecution) -> dict[str, Any]:
        """保存真实业务输入；选举回执属于本次调度，不进入业务内容"""
        payload = execution.receipt.payload
        result = {
            key: value for key, value in payload.items() if key not in {"reservation_id", "model_id", "attempt_number"}
        }
        result["paragraphs"] = [
            {
                key: getattr(row, key)
                for key in ("chapter_id", "paragraph_id", "local_start_char", "local_end_char", "text")
            }
            for row in payload["paragraphs"]
        ]
        return result

    def _save(self, execution: WorkExecution, session: Session) -> str:
        if not execution.finished:
            raise ValueError("只有成功 finish 的 work 可以保存")
        annotation_id = stable_uuid(self.run_id, execution.work_id)
        existing = session.get(AnalysisOutput, annotation_id)
        if existing is not None:
            if existing.invocation_id != execution.invocation_id or existing.payload != execution.output():
                raise ValueError(f"work_id={execution.work_id} 已有另一份不可变结果")
            return annotation_id
        payload = execution.receipt.payload
        session.add(
            AnalysisOutput(
                output_id=annotation_id,
                kind="chapter_annotation",
                run_id=self.run_id,
                chapter_id=payload["chapter_id"],
                role=payload["role"],
                work_id=execution.work_id,
                invocation_id=execution.invocation_id,
                actual_input=self.actual_input(execution),
                payload=execution.output(),
            )
        )
        session.flush()
        self.event_trees.save_work(session, execution, annotation_id)
        self.fact_graph.save_work(session, execution, annotation_id)
        self._save_dialogues(session, execution)
        self.case_pool.save_work(session, execution)
        return annotation_id

    async def confirm(self, message: Message) -> None:
        execution = self._execution(message)
        async with self.lock:
            self.fact_graph.confirm(execution.work_id, execution.invocation_id)
            self.event_trees.confirm(execution.work_id, execution.invocation_id)
            self.case_pool.confirm(execution.work_id, execution.invocation_id)
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
                percent=10 + current / total * 70,
                sub_percent=current / total * 100,
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
            self.fact_graph.rollback(execution.work_id, execution.invocation_id)
            self.event_trees.rollback(execution.work_id, execution.invocation_id)
            self.case_pool.rollback(execution.work_id, execution.invocation_id)

    def freeze(self, execution: WorkExecution) -> None:
        """在单条 finish 成功后固定自身贡献，数据库线程不遍历并发修改的全书字典"""
        author = (execution.work_id, execution.invocation_id)
        facts: dict[str, Any] = self.fact_graph.drain_ops(*author)
        names = {op["name"] for op in facts["entity_ops"]}
        for op in facts["relation_assert_ops"]:
            names.update((op["from_entity"], op["to_entity"]))
        output = execution.output()
        names.update(item["character"] for item in output["character_observations"])
        names.update(item["speaker"] for item in output["dialogues"] if item["speaker"])
        for event in output["events"]:
            names.update(item["entity"] for item in event["participants"])
        facts["entities"] = {
            self.fact_graph.entity_id(name): {
                "entity_id": self.fact_graph.entity_id(name),
                "name": name,
                "entity_type": str(self.fact_graph.entity_type(name)),
            }
            for name in names
        }
        self.fact_graph.reference_entities(author, list(facts["entities"].values()))
        execution.contributions = {
            "facts": facts,
            "events": {
                "nodes": deepcopy(
                    {key: value for key, value in self.event_trees.nodes.items() if value["author"] == author}
                ),
                "connections": deepcopy(
                    {key: value for key, value in self.event_trees.connections.items() if value["author"] == author}
                ),
            },
            "cases": {
                "registrations": deepcopy(
                    {
                        identifier: self.case_pool.cases[identifier]
                        for identifier in self.case_pool.registrations.get(author, set())
                    }
                ),
                "deliveries": deepcopy(self.case_pool.deliveries.get(author, [])),
            },
        }

    def _save_dialogues(self, session: Session, execution: WorkExecution) -> None:
        from src.fact_graph.graph import mention_uuid
        from src.storage.models import DialogueRecord

        if execution.ledger.role not in {"solo", "evidence"}:
            return
        for content in execution.output()["dialogues"]:
            identifier = stable_uuid(self.run_id, execution.work_id, content["candidate_key"])
            session.add(
                DialogueRecord(
                    dialogue_id=identifier,
                    run_id=self.run_id,
                    chapter_id=execution.ledger.current_chapter_id,
                    candidate_key=content["candidate_key"],
                    content=content["content"],
                    start=content["start"],
                    end=content["end"],
                    speaker=mention_uuid(self.run_id, execution.ledger.current_chapter_id, content["speaker"])
                    if content["speaker"]
                    else None,
                    tone=content["tone"],
                    is_inner_monologue=content["is_inner_monologue"],
                    confidence="high",
                    author_work_id=execution.work_id,
                )
            )
        session.flush()

    async def check(self, message: Message) -> bool:
        execution = self._execution(message)

        def query() -> bool:
            from sqlalchemy import select

            from src.storage.models import (
                AnnotationWork,
                BookCase,
                DialogueRecord,
                EventEdge,
                EventNode,
                GraphFact,
            )

            with self.session_factory() as session:
                work = session.get(AnnotationWork, execution.work_id)
                if work is None or any(
                    getattr(work, name) != value
                    for name, value in {
                        "run_id": self.run_id,
                        "chapter_id": execution.receipt.payload["chapter_id"],
                        "role": execution.receipt.payload["role"],
                        "invocation_id": execution.invocation_id,
                        "state": "saved",
                    }.items()
                ):
                    return False
                row = session.get(AnalysisOutput, stable_uuid(self.run_id, message.work_id))
                if (
                    row is None
                    or row.invocation_id != message.invocation_id
                    or row.payload != execution.output()
                    or row.actual_input != self.actual_input(execution)
                ):
                    return False
                facts = list(
                    session.execute(
                        select(GraphFact).where(
                            GraphFact.author_work_id == execution.work_id, GraphFact.run_id == self.run_id
                        )
                    ).scalars()
                )
                expected = execution.contributions["facts"]
                references: list[dict[str, Any]] = []
                for fact in facts:
                    if fact.fact_type == "entity_reference":
                        value = fact.value
                        if not isinstance(value, dict) or "entity_id" not in value:
                            return False
                        references.append(value)
                references.sort(key=lambda value: value["entity_id"])
                if references != sorted(expected["entities"].values(), key=lambda value: value["entity_id"]):
                    return False
                for kind, operations in (
                    ("entity", expected["entity_ops"]),
                    ("relation", expected["relation_assert_ops"]),
                    ("character_observation", execution.output()["character_observations"]),
                ):
                    actual = sorted(
                        (fact for fact in facts if fact.fact_type == kind),
                        key=lambda fact: fact.content["operation_order"],
                    )
                    if [fact.value for fact in actual] != operations:
                        return False
                for identifier, value in execution.contributions["events"]["nodes"].items():
                    node = session.get(EventNode, identifier)
                    content = value["content"]
                    participants = [
                        {**item, "entity": expected["entities"][self.fact_graph.entity_id(item["entity"])]}
                        for item in content["participants"]
                    ]
                    if (
                        node is None
                        or node.producer_invocation_id != execution.invocation_id
                        or node.author_work_id != execution.work_id
                        or node.description != content["description"]
                        or node.participants != participants
                        or node.anchor_paragraph_ids != [content["evidence_paragraph_id"]]
                    ):
                        return False
                connections = deepcopy(execution.contributions["events"]["connections"])
                for identifier, value in execution.contributions["events"]["nodes"].items():
                    content = value["content"]
                    if content["parent_node_id"]:
                        edge_id = stable_uuid(
                            self.run_id, execution.work_id, content["parent_node_id"], identifier, content["cause_role"]
                        )
                        connections[edge_id] = {
                            "parent": content["parent_node_id"],
                            "child": identifier,
                            "type": content["cause_role"],
                        }
                for identifier, value in connections.items():
                    edge = session.get(EventEdge, identifier)
                    if (
                        edge is None
                        or edge.author_work_id != execution.work_id
                        or edge.source_event_id != value["parent"]
                        or edge.target_event_id != value["child"]
                        or (edge.cause_role or edge.edge_type) != value["type"]
                    ):
                        return False
                case_ids = set(execution.contributions["cases"]["registrations"])
                case_ids.update(item["case_id"] for item in execution.contributions["cases"]["deliveries"])
                for identifier in case_ids:
                    state = session.get(BookCase, identifier)
                    facts = [
                        fact for fact in execution.contributions["cases"]["deliveries"] if fact["case_id"] == identifier
                    ]
                    if state is None or state.contributions.get(execution.work_id) != {
                        "invocation_id": execution.invocation_id,
                        "deliveries": facts,
                    }:
                        return False
                if execution.ledger.role in {"solo", "evidence"}:
                    dialogues = list(
                        session.execute(
                            select(DialogueRecord).where(DialogueRecord.author_work_id == execution.work_id)
                        ).scalars()
                    )
                    if {row.candidate_key for row in dialogues} != {
                        item["candidate_key"] for item in execution.output()["dialogues"]
                    }:
                        return False
                    from src.fact_graph.graph import mention_uuid

                    by_key = {item.candidate_key: item for item in dialogues}
                    for content in execution.output()["dialogues"]:
                        dialogue = by_key[content["candidate_key"]]
                        speaker = (
                            mention_uuid(self.run_id, execution.ledger.current_chapter_id, content["speaker"])
                            if content["speaker"]
                            else None
                        )
                        if dialogue.speaker != speaker or any(
                            getattr(dialogue, key) != content[key]
                            for key in ("content", "start", "end", "tone", "is_inner_monologue")
                        ):
                            return False
                return True

        return await asyncio.to_thread(query)

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
        if not await self.check(message):
            raise ValueError(f"work_id={message.work_id} 保存结果不一致，不能恢复确认")

        def load() -> tuple[Any, Any, Any]:
            with self.session_factory() as session:
                args = (
                    session,
                    execution.work_id,
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
        from sqlalchemy import delete, select

        from src.storage.models import DialogueRecord

        session, discard = data["session"], set(data["discard"])
        self.fact_graph.discard_storage(session, discard)
        self.event_trees.discard_storage(session, discard)
        session.execute(
            delete(DialogueRecord).where(
                DialogueRecord.run_id == self.run_id, DialogueRecord.author_work_id.in_(discard)
            )
        )
        session.execute(
            delete(AnalysisOutput).where(
                AnalysisOutput.run_id == self.run_id,
                AnalysisOutput.kind == "chapter_annotation",
                AnalysisOutput.work_id.in_(discard),
            )
        )
        session.flush()
        records = list(
            session.execute(
                select(AnalysisOutput).where(
                    AnalysisOutput.run_id == self.run_id, AnalysisOutput.kind == "chapter_annotation"
                )
            ).scalars()
        )
        self.fact_graph.rebuild_storage(session)
        self.event_trees.rebuild_storage(session)
        self.fact_graph.restore_storage(session, records)
        self.event_trees.restore_storage(session, records)
        self.case_pool.restore_storage(session, discard)

    def close(self) -> None:
        for topic in (
            "agent.execute",
            "agent.save",
            "agent.confirm",
            "agent.saved_progress",
            "agent.cancel",
            "agent.abort",
            "agent.check",
            "agent.recover",
        ):
            self.bus.unhandle(topic, self.address)
