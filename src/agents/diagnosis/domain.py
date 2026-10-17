"""诊断工作的领域权限、候选贡献和一次发布，不调用协调模型"""

from __future__ import annotations

import json
import threading
from typing import Any, cast

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.case_pool import CasePool
from src.diagnosis.queries import DiagnosisQueries
from src.diagnosis.schema import AgentAnalysis
from src.event_trees.organization import (
    CompleteEventDraft,
    ConflictDraft,
    ContainmentDraft,
    DeclarationComparisonDraft,
    DeclarationReviewDraft,
    EventArcLinkDraft,
    EventOrganizationDraft,
    EventOutcomeDraft,
    EventOutcomeLinkDraft,
    EventReviewDraft,
    NarrativeArcDraft,
    RelationDraft,
    StructureReviewDraft,
    record_payloads,
    register_diagnosis_execution,
    register_diagnosis_session,
    register_diagnosis_work,
    snapshot_digest,
)
from src.utils.identity import stable_digest

from .evidence import DiagnosisEvidenceLedger
from .persistence import save_diagnosis_result
from .program_runtime import DiagnosisProgramRuntime
from .prompts import build_diagnosis_system_prompt
from .tools import build_diagnosis_tools
from .work_planning import WorkPhase, WorkSpec
from .work_runtime import DiagnosisWorkContext, DiagnosisWorkCorrections

_GROUPS: dict[str, type[BaseModel]] = {
    "events": CompleteEventDraft,
    "relations": RelationDraft,
    "containments": ContainmentDraft,
    "declaration_reviews": DeclarationReviewDraft,
    "declaration_comparisons": DeclarationComparisonDraft,
    "reviewed_events": EventReviewDraft,
    "arcs": NarrativeArcDraft,
    "event_arc_links": EventArcLinkDraft,
    "outcomes": EventOutcomeDraft,
    "event_outcome_links": EventOutcomeLinkDraft,
    "conflicts": ConflictDraft,
    "structure_reviews": StructureReviewDraft,
}


def _record_key(group: str, item: Any) -> Any:
    if group == "structure_reviews":
        return tuple(sorted((item.source_event_id, item.target_event_id)))
    if group == "containments":
        return item.parent_event_id, item.child_event_id
    if group == "event_arc_links":
        return item.event_id, item.arc_id
    if group == "event_outcome_links":
        return item.event_id, item.outcome_id
    fields = {
        "events": "event_id",
        "relations": "relation_id",
        "declaration_reviews": "declaration_id",
        "reviewed_events": "event_id",
        "arcs": "arc_id",
        "outcomes": "outcome_id",
        "conflicts": "conflict_id",
    }
    return getattr(item, fields[group])


class _WorkDraft:
    """每次原语调用绑定实际工作，异步读取不会串改其他会话的写入来源"""

    def __init__(self, domain: DiagnosisDomain, work: WorkSpec, invocation: str) -> None:
        self.domain, self.work, self.invocation = domain, work, invocation

    def __getattr__(self, name: str) -> Any:
        draft = self.domain.draft
        value = getattr(draft, name)
        if not callable(value):
            return value

        def invoke(*args: Any, **kwargs: Any) -> Any:
            draft.work_id, draft.producer_invocation_id = self.work.work_id, self.invocation
            identity_ops = {"identity", "review_declarations", "compare_declarations"}
            structure_ops = {"event", "contain", "relate_events", "review_events", "structure_review"}
            narrative_ops = {"register_arc", "link_event_arc", "register_outcome", "link_event_outcome"}
            # 2026-10-15 用户裁定：比较/结构/叙事独立 work 全部删除，同一事件工作在
            # 身份会话与结构会话两段完成各自义务，收尾报告工作独占叙事与报告写面
            draft.responsible_ids = set(self.work.responsible_ids) if self.work.role == "event" else None
            if name in identity_ops and self.work.role != "event":
                raise ValueError("只有事件工作可以提交身份、事实核对或来源比较")
            if name in structure_ops and self.work.role != "event":
                raise ValueError("只有事件工作可以提交事件结构写入")
            if name in narrative_ops and self.work.role != "report":
                raise ValueError("叙事写入只能由收尾报告工作完成")
            if name == "structure_review":
                pair = tuple(sorted((kwargs["source_event_id"], kwargs["target_event_id"])))
                if pair not in self.domain._structure_pairs(self.work):
                    raise ValueError("结构比较不属于本 work 的已派发事项")
            if name in {"contain", "relate_events"}:
                source = kwargs["parent_event_id"] if name == "contain" else kwargs["source_id"]
                target = kwargs["child_event_id"] if name == "contain" else kwargs["target_id"]
                pair = min(source, target), max(source, target)
                owned_new = any(self.domain.draft.events[key].source_work_id == self.work.work_id
                                and not self.domain.draft.events[key].declaration_ids
                                for key in (source, target) if key in self.domain.draft.events)
                if pair not in self.domain._structure_pairs(self.work) and not owned_new:
                    raise ValueError("结构写入端点不是本 work 的已派发事项或本工作新建父事件")
            if name == "review_events":
                allowed = {key for pair in self.domain._structure_pairs(self.work) for key in pair}
                allowed.update(item.event_id for item in draft.events.values()
                               if item.source_work_id == self.work.work_id)
                allowed.update(self.domain._written_structure_endpoints(self.work))
                if not set(args[0] if args else kwargs["event_ids"]) <= allowed:
                    raise ValueError("事件核对端点不是本 work 的责任范围")
            return value(*args, **kwargs)

        def locked_invoke(*args: Any, **kwargs: Any) -> Any:
            with self.domain.lock:
                return invoke(*args, **kwargs)
        return locked_invoke


class DiagnosisDomain:
    """冻结真实章级来源，工作只保存自己产生的候选，最终同一事务发布"""

    def __init__(
        self,
        *,
        session: Session,
        run_id: str,
        novel_id: str,
        execution_id: str,
        novel_title: str | None,
        model_id: str,
    ) -> None:
        self.session, self.run_id, self.novel_id, self.execution_id = session, run_id, novel_id, execution_id
        self.novel_title, self.model_id = novel_title, model_id
        self.lock = threading.RLock()
        self.read_sessions: dict[str, Session] = {}
        self.draft = EventOrganizationDraft(session, run_id, execution_id)
        self.sources = self.draft._declarations()
        self.source_hash = snapshot_digest(self.sources)
        self.case_pool = CasePool(run_id)
        self.case_pool.load_storage(session)
        self.reports: dict[str, dict[str, Any]] = {}
        self.ledgers: dict[str, DiagnosisEvidenceLedger] = {}
        # 2026-10-15 用户裁定「复用标注工具」「没权限」：三类案例处置写承认接
        self.case_writers: dict[str, Any] = {}
        self._case_graph_value: Any | None = None
        self._case_dialogue_value: list[Any] | None = None
        self.work: dict[str, WorkSpec] = {}
        self.report_bindings: dict[str, str] = {}
        self.initial: list[WorkSpec] | None = None
        # 诊断整轮身份先短事务登记：失败轮次同样保留审计身份，不写任何 checkpoint
        self._short_transaction(
            lambda short: register_diagnosis_session(short, run_id=run_id, session_id=execution_id)
        )

    def _short_transaction(self, action: Any) -> Any:
        """领域短事务：登记会话/work/执行身份后再由正式事务保存业务产物"""
        bind = self.session.get_bind()
        with Session(bind=getattr(bind, "engine", bind)) as short, short.begin():
            return action(short)

    def register_work_identity(self, work: WorkSpec) -> None:
        """派发前先短事务登记会话与 work 身份：审计登记真实执行前 work 必须已存在

        执行行由审计记录器在派发时创建，这里只保证它引用的 work 身份已经落库。
        """

        def action(short: Session) -> None:
            register_diagnosis_session(short, run_id=self.run_id, session_id=self.execution_id)
            register_diagnosis_work(
                short, session_id=self.execution_id, work_id=work.work_id, role=work.role
            )

        self._short_transaction(action)

    def next_dispatch_attempt(self, work_id: str) -> int:
        """本轮派发的真实尝试序号：该 work 既有执行事实数 + 1（跨轮累计，不重置）

        登记契约要求 (work, attempt) 唯一（"该次尝试已有真实执行"）；续跑重派是
        新的真实尝试，必须推进序号才能登记自己的执行事实（2026-10-17 run 52cbb1ac）。
        """
        from sqlalchemy import func, select

        from src.storage.models import Execution

        count = self.session.scalar(
            select(func.count()).select_from(Execution).where(Execution.work_id == work_id)
        )
        return int(count or 0) + 1

    def _register_attempt(self, work: WorkSpec, invocation: str, attempt_number: int) -> None:
        """每次真实尝试先短事务登记 work 身份与执行事实，审计与产物都引用同一身份"""

        def action(short: Session) -> None:
            register_diagnosis_session(short, run_id=self.run_id, session_id=self.execution_id)
            register_diagnosis_work(
                short, session_id=self.execution_id, work_id=work.work_id, role=work.role
            )
            register_diagnosis_execution(
                short, work_id=work.work_id, execution_id=invocation, attempt_number=attempt_number
            )

        self._short_transaction(action)

    def _declaration_positions(self) -> dict[str, int]:
        """声明按真实来源章序与段序的稳定顺序，比较配对的迟早由它裁定"""
        return {identifier: position for position, identifier in enumerate(self.sources)}

    def _work_messages(self, role: str, responsible: tuple[str, ...],
                       material: dict[str, Any]) -> list[Any]:
        """规划和发起请求使用完全相同的消息封装"""
        return [SystemMessage(content=build_diagnosis_system_prompt(self.novel_title)),
                HumanMessage(content=json.dumps({"role": role,
                    "responsible_ids": responsible, "materials": material}, ensure_ascii=False))]

    def initial_work(self) -> list[WorkSpec]:
        """2026-10-15 用户裁定「建一个事件进一个池」「切分不要使用max_tokens」：切分只保留
        事件边界，每个声明一个事件工作，payload 精简为 {source_hash, event_ids}"""
        if self.initial is not None:
            return self.initial
        self.initial = [
            WorkSpec(self.run_id, "event", (declaration_id,),
                     {"source_hash": self.source_hash, "event_ids": [declaration_id]})
            for declaration_id in self.sources
        ]
        self.work.update({item.work_id: item for item in self.initial})
        return self.initial

    def _comparison_receipts(self, responsible: tuple[str, ...]) -> list[dict[str, Any]]:
        """交接是有来源的判断索引，原理由和原文仍留在比较候选与声明读取面"""
        return [{"source_declaration_id": source, "target_declaration_id": target,
                 "disposition": item.disposition, "source_work_id": item.source_work_id,
                 "producer_invocation_id": item.producer_invocation_id}
                for (source, target), item in self.draft.declaration_comparisons.items()
                if source in responsible or target in responsible]

    def clear_work_candidates(self, work_id: str) -> None:
        """修正重派从零会话开始，程序侧清退本工作旧候选，旧判断只在审计保留"""
        with self.lock:
            for group in _GROUPS:
                target = getattr(self.draft, group)
                for key in [key for key, item in target.items() if item.source_work_id == work_id]:
                    del target[key]
            for key in [key for key, item in self.draft.revisions.items() if item.source_work_id == work_id]:
                del self.draft.revisions[key]
            self.reports.pop(work_id, None)
            self.ledgers.pop(work_id, None)

    def _snapshot(self, work: WorkSpec, invocation: str) -> dict[str, Any]:
        with self.lock:
            return self._snapshot_locked(work, invocation)

    def _snapshot_locked(self, work: WorkSpec, invocation: str) -> dict[str, Any]:
        groups = {
            group: [
                item.model_dump(mode="json")
                for item in getattr(self.draft, group).values()
                if item.source_work_id == work.work_id
            ]
            for group in _GROUPS
        }
        author = work.work_id, invocation
        return {
            "source_hash": self.source_hash,
            "groups": groups,
            "report": self.reports.get(work.work_id, {}),
            "report_binding": self.report_bindings.get(work.work_id),
            "evidence": self.ledgers[work.work_id].to_dict(),
            "cases": {
                "cases": list(self.case_pool.cases.values()),
                "sequence": self.case_pool._sequence,
                "runtime": {
                    key: {**value, "owner": list(value["owner"]) if value.get("owner") else None}
                    for key, value in self.case_pool.case_runtime.items()
                    if value.get("owner") == author
                },
                "created": sorted(self.case_pool.created.get(author, set())),
                "registrations": sorted(self.case_pool.registrations.get(author, set())),
                "deliveries": self.case_pool.deliveries.get(author, []),
            },
        }

    def _restore(self, work: WorkSpec, invocation: str, data: dict[str, Any]) -> None:
        with self.lock:
            self._restore_locked(work, invocation, data)

    def _restore_locked(self, work: WorkSpec, invocation: str, data: dict[str, Any]) -> None:
        if not data:
            return
        if data.get("source_hash") != self.source_hash:
            raise ValueError("诊断检查点来源清单已改变，不能转换旧候选")
        for group, records in data["groups"].items():
            target = getattr(self.draft, group)
            # 恢复只替换本作者候选，不能回滚其他已接受工作
            for key in [key for key, item in target.items() if item.source_work_id == work.work_id]:
                del target[key]
            for payload in records:
                item: Any = _GROUPS[group].model_validate(payload)
                if item.source_work_id != work.work_id or item.producer_invocation_id != invocation:
                    raise ValueError("候选实际生产者与检查点不一致")
                if group == "declaration_comparisons":
                    for identifier in item.target_declaration_ids:
                        target[(item.source_declaration_id, identifier)] = item
                else:
                    target[_record_key(group, item)] = item
        report = self.reports.setdefault(work.work_id, {})
        report.clear()
        report.update(data["report"])
        if data.get("report_binding"):
            self.report_bindings[work.work_id] = data["report_binding"]
        self.ledgers[work.work_id].tool_calls = list(data["evidence"]["tool_calls"])
        author = work.work_id, invocation
        self.case_pool._sequence = max(self.case_pool._sequence, data["cases"]["sequence"])
        self.case_pool.begin(*author)
        for case in data["cases"]["cases"]:
            existing = self.case_pool.cases.get(case["case_id"])
            if existing is not None and existing != case:
                raise ValueError("案例来源内容与检查点冲突")
            self.case_pool.cases[case["case_id"]] = case
            self.case_pool.case_runtime.setdefault(case["case_id"], {"state": "pending", "owner": None})
        self.case_pool.created[author] = set(data["cases"]["created"])
        self.case_pool.registrations[author] = set(data["cases"]["registrations"])
        self.case_pool.deliveries[author] = data["cases"]["deliveries"]
        for key, state in data["cases"].get("runtime", {}).items():
            current_owner = self.case_pool.case_runtime[key].get("owner")
            if current_owner is not None and current_owner != author:
                raise ValueError("案例检查点与其他工作占用冲突")
            self.case_pool.case_runtime[key] = {**state, "owner": tuple(state["owner"]) if state["owner"] else None}

    def _identity_gaps(self, work: WorkSpec) -> list[str]:
        """一次列全身份段缺口；逐条 raise 会让模型每回合只补一条，预算在补齐途中耗尽
        （run 52cbb1ac 第 9 轮：工作 68fb7951 第 9 回合 finish 只报一条比较缺口，
        第 10 回合补完该条后又被下一条挡住，触顶失败）"""
        position = self._declaration_positions()
        gaps: list[str] = []
        for source in work.responsible_ids:
            missing = [
                target
                for target in position
                if position[target] > position.get(source, -1)
                and (source, target) not in self.draft.declaration_comparisons
            ]
            if missing:
                gaps.append(f"来源比较尚未明确判断: source={source} targets={missing}")
        for identifier in work.responsible_ids:
            if identifier not in self.draft.declaration_reviews:
                gaps.append(f"声明缺少事实核对: declaration_id={identifier}")
            if any(identifier in item.declaration_ids for item in self.draft.events.values()):
                continue
            if not any(
                target == identifier and item.disposition == "same_event"
                for (_, target), item in self.draft.declaration_comparisons.items()
            ):
                gaps.append(f"声明缺少身份判断或带证据的交接: declaration_id={identifier}")
        return gaps

    def _structure_pairs(self, work: WorkSpec) -> set[tuple[str, str]]:
        events = sorted(
            (item for item in self.draft.events.values() if item.declaration_ids),
            key=lambda item: (item.first_text_position, item.event_id),
        )
        return {
            (min(source.event_id, target.event_id), max(source.event_id, target.event_id))
            for index, source in enumerate(events)
            if source.source_work_id == work.work_id
            for target in events[index + 1 :]
        }

    def _written_structure_endpoints(self, work: WorkSpec) -> set[str]:
        return {
            key for edge in self.draft.containments.values() if edge.source_work_id == work.work_id
            for key in (edge.parent_event_id, edge.child_event_id)
        } | {
            key for edge in self.draft.relations.values() if edge.source_work_id == work.work_id
            for key in (edge.source_id, edge.target_id)
        }

    def _structure_gaps(self, work: WorkSpec) -> list[str]:
        """一次列全结构段缺口，理由与身份段相同：拒收回执必须覆盖当前全部未满足义务"""
        produced = [item for item in self.draft.events.values() if item.source_work_id == work.work_id]
        checked = {item.event_id for item in produced} | self._written_structure_endpoints(work)
        gaps: list[str] = []
        unreviewed: list[str] = []
        for identifier in sorted(checked):
            review = self.draft.reviewed_events.get(identifier)
            if review is None or review.snapshot_hash != self.draft.event_snapshot(identifier):
                unreviewed.append(identifier)
        if unreviewed:
            gaps.append(f"事件结构须核对实际版本: event_ids={unreviewed}")
        for item in produced:
            if (
                not item.declaration_ids
                and sum(edge.parent_event_id == item.event_id for edge in self.draft.containments.values()) < 2
            ):
                gaps.append(f"跨章父事件须显式包含独立子事件: event_id={item.event_id}")
        unhandled = [
            pair
            for pair in sorted(self._structure_pairs(work))
            if self.draft.structure_reviews.get(pair) is None
            or self.draft.structure_reviews[pair].source_work_id != work.work_id
            or self.draft.structure_reviews[pair].snapshot_hash != self.draft.pair_snapshot(*pair)
        ]
        if unhandled:
            gaps.append(f"已派发结构事项须明确处置实际版本: endpoints={unhandled}")
        return gaps

    def _case_graph(self) -> Any:
        """诊断期挂接全书事实图：先按存储恢复登记金链，再承接三类案例处置写入"""
        from src.fact_graph.graph import FactGraph

        if self._case_graph_value is None:
            graph = FactGraph(run_scope=self.run_id)
            graph.load_registry(self.session)
            self._case_graph_value = graph
        return self._case_graph_value

    def _case_dialogue_candidates(self) -> list[Any]:
        """对话候选来自持久化对话记录，顺序确定（章序+候选键），供 write_dialogue 逐号判定"""
        from src.event_trees import storage_map as smap
        from src.fact_graph.inputs import DialogueCandidate

        if self._case_dialogue_value is None:
            self._case_dialogue_value = [
                DialogueCandidate(
                    candidate_key=row["candidate_key"],
                    chapter_id=row["chapter_id"],
                    start=row["start"],
                    end=row["end"],
                    content=row["content"],
                    parse_status="dialogue_line",
                )
                for row in smap.dialogue_candidate_rows(self.session, self.run_id)
            ]
        return list(self._case_dialogue_value)

    def _declaration_chapter(self, item: Any) -> int:
        """未决登记的归属章=声明来源章；无从判定时归第一章"""
        for identifier in item.declaration_ids:
            declaration = self.sources.get(identifier)
            if declaration is None:
                continue
            if declaration.get("chapter_id") is not None:
                return int(declaration["chapter_id"])
            if declaration.get("chapter_order") is not None:
                for row in self.sources.values():
                    if (
                        row.get("chapter_order") == declaration.get("chapter_order")
                        and row.get("chapter_id") is not None
                    ):
                        return int(row["chapter_id"])
        for position in sorted(self.sources.values(), key=lambda row: row.get("chapter_order") or 0):
            if position.get("chapter_id") is not None:
                return int(position["chapter_id"])
        return 0

    def _work_source_chapter(self, work: Any) -> int:
        """事件工作的写入归属章=责任声明所在章；报告工作与无来源情形归第一章"""
        for identifier in work.responsible_ids:
            declaration = self.sources.get(identifier)
            if declaration is not None and declaration.get("chapter_id") is not None:
                return int(declaration["chapter_id"])
        for position in sorted(self.sources.values(), key=lambda row: row.get("chapter_order") or 0):
            if position.get("chapter_id") is not None:
                return int(position["chapter_id"])
        return 0

    def build_context(
        self, work: WorkSpec, phase: WorkPhase, observer: Any, corrections: dict[str, Any] | None
    ) -> DiagnosisWorkContext:
        with self.lock:
            if corrections is not None:
                self.clear_work_candidates(work.work_id)
            return self._build_context_locked(work, phase, observer, corrections)

    def _build_context_locked(
        self, work: WorkSpec, phase: WorkPhase, observer: Any, corrections: dict[str, Any] | None
    ) -> DiagnosisWorkContext:
        invocation = str(getattr(observer, "invocation_id", None) or stable_digest("diagnosis_execution", work.work_id))
        # 审计上下文里的 execution_id 才是持久工作调用身份，不能用报告身份冒充全部生产者
        context = getattr(observer, "_context", None)
        attempt_number = 1
        if isinstance(context, dict):
            invocation = str(context.get("execution_id") or invocation)
            attempt_number = int(context.get("attempt_number") or 1)
        # 真实尝试先短事务登记，审计与正式产物引用同一执行身份
        self._register_attempt(work, invocation, attempt_number)
        ledger = self.ledgers.setdefault(work.work_id, DiagnosisEvidenceLedger())
        report = self.reports.setdefault(work.work_id, {})
        proxy = _WorkDraft(self, work, invocation)
        if work.work_id not in self.read_sessions:
            bind = self.session.get_bind()
            self.read_sessions[work.work_id] = Session(bind=getattr(bind, "engine", bind))
        tools = build_diagnosis_tools(
            self.read_sessions[work.work_id],
            self.run_id,
            evidence_ledger=ledger,
            organization_draft=cast(EventOrganizationDraft, proxy),
            report_draft=report,
            case_pool=self.case_pool,
            execution_id=self.execution_id,
            case_writes_graph=self._case_graph(),
            case_source_chapter=self._work_source_chapter(work),
            case_dialogue_candidates=self._case_dialogue_candidates(),
            case_writer_store=self.case_writers,
            work_id=work.work_id,
            producer_invocation_id=invocation,
        )
        for tool in tools:
            if tool.name != "write_diagnosis":
                continue
            original = tool.func

            def write_report(*args: Any, _original: Any = original, **kwargs: Any) -> Any:
                if work.role != "report":
                    raise ValueError("本工作没有全书报告提交责任")
                result = _original(*args, **kwargs)
                self.report_bindings[work.work_id] = self._narrative_snapshot()
                return result

            tool.func = write_report
        for tool in tools:
            original_function = tool.func
            if original_function is not None:
                def locked_tool(*args: Any, _function: Any = original_function, **kwargs: Any) -> Any:
                    with self.lock:
                        return _function(*args, **kwargs)
                tool.func = locked_tool
        program = DiagnosisProgramRuntime(tools, observer=observer, invocation_id=invocation)
        material: dict[str, Any] = dict(work.input_payload)
        if phase == "structure":
            # 2026-10-15 结构独立 work 已删：事件工作自行取材，结构写入只对自己拥有的端点开放
            material = {
                **material,
                "identity_snapshot": self.draft.identity_snapshot,
            }
        else:
            events = [item.model_dump(mode="json") for item in self.draft.events.values()]
            material = {
                **material,
                "structure_snapshot": self.draft.structure_snapshot,
                "catalog": [{key: row[key] for key in ("event_id", "title", "problem", "status")} for row in events],
                "arcs": [{"arc_id": item.arc_id, "title": item.title} for item in self.draft.arcs.values()],
                "outcomes": [
                    {"outcome_id": item.outcome_id, "title": item.title} for item in self.draft.outcomes.values()
                ],
            }
        if work.role == "event" and phase == "identity":
            receipts = self._comparison_receipts(work.responsible_ids)
            if receipts:
                material["comparisons"] = receipts
        if corrections is not None:
            material["corrections"] = corrections

        def complete() -> list[str]:
            if phase == "identity":
                return self._identity_gaps(work)
            if phase == "structure":
                return self._structure_gaps(work)
            try:
                ledger.require_evidence()
                analysis = AgentAnalysis.model_validate(report.get("analysis", {}))
                expected = {
                    int(row["topic_id"]) for row in DiagnosisQueries(self.session).fetch_topic_words(self.run_id)
                }
                if {int(key) for key in analysis.topic_labels} != expected:
                    raise ValueError("报告主题键必须与真实主题数据完全一致")
                if self.report_bindings.get(work.work_id) != self._narrative_snapshot():
                    raise ValueError("报告绑定的叙事快照已改变，须明确核对后重新提交报告")
            except ValueError as exc:
                return [str(exc)]
            return []

        messages = self._work_messages(work.role, work.responsible_ids, material)
        return DiagnosisWorkContext(program, messages, lambda: self._complete_locked(complete))

    def _complete_locked(self, check: Any) -> list[str]:
        with self.lock:
            return check()

    def close(self) -> None:
        """关闭每份工作独立的取证会话，不提交任何领域事务"""
        with self.lock:
            for session in self.read_sessions.values():
                session.close()
            self.read_sessions.clear()

    def _correct(self, phase: str, error: ValueError) -> None:
        # 失败收尾沿异常链读取冲突所属阶段，不把一度出现但已修正的冲突登记为未决
        error.diagnosis_phase = phase  # type: ignore[attr-defined]
        affected = tuple(getattr(error, "work_ids", ()))
        if not affected:
            # 缺乏可靠责任归属时停止，不能把无关已完成工作或其预算卷入修正
            raise error
        raise DiagnosisWorkCorrections(
            affected,
            {
                "field": phase,
                "actual": str(error),
                "expected": "依据真实来源显式修正自己提交的相冲突候选；不得改动其他 work 的已接受声明",
            },
        ) from error

    def _register_unresolved_cases(self, error: BaseException) -> None:
        """只在最终失败时为仍在异常链上的冲突登记模板案例，来源候选保持原样"""
        seen: set[int] = set()
        current: BaseException | None = error
        conflicts: list[tuple[str, set[str]]] = []
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            affected = set(getattr(current, "work_ids", ()))
            phase = getattr(current, "diagnosis_phase", None)
            if affected and phase:
                conflicts.append((str(phase), affected))
            current = current.__cause__ or current.__context__
        if not conflicts:
            return
        author = (f"diagnosis-pending:{self.execution_id}", self.execution_id)
        self.case_pool.begin(*author)
        for phase, affected in conflicts:
            for item in self.draft.events.values():
                if item.source_work_id not in affected:
                    continue
                paragraphs = sorted({ref.paragraph_id for ref in item.evidence})
                for paragraph_id in paragraphs:
                    # 超长节点名分条完整保留，每条均携带身份、类型、原因和证据，绝不切掉事实
                    prefix = f"{item.event_id}|event|{phase}_conflict|段{paragraph_id}|名"
                    width = 100 - len(prefix) - 18
                    if width <= 0:
                        raise ValueError("未决案例来源标识超出描述约束，不能截断事实")
                    chunks = [item.title[index:index + width] for index in range(0, len(item.title), width)]
                    for index, chunk in enumerate(chunks, 1):
                        self.case_pool.register_case(
                            case_type="event",
                            description=f"{prefix}{index}/{len(chunks)}:{chunk}",
                            payload={
                                "event_id": item.event_id,
                                "name": item.title,
                                "reason": f"{phase}_conflict",
                                "chapter_id": self._declaration_chapter(item),
                            },
                            author=author,
                        )

    def retain_pending_cases(self, error: BaseException) -> None:
        """失败或取消只短事务保留登记，不采用候选交付、不发布事件或报告"""
        from sqlalchemy import select

        from src.case_pool.contributions import CaseContribution
        from src.storage.models import DiagnosisReport

        with self.lock:
            self._register_unresolved_cases(error)
            contributions = [
                CaseContribution(
                    self.run_id,
                    author[0],
                    author[1],
                    json.dumps(
                        {
                            "created_case_ids": sorted(self.case_pool.created.get(author, set())),
                            "registrations": {
                                key: self.case_pool.cases[key]
                                for key in sorted(self.case_pool.registrations.get(author, set()))
                            },
                            "deliveries": [],
                        },
                        ensure_ascii=False,
                    ),
                )
                for author in sorted(self.case_pool.executions)
                if author not in self.case_pool.saved and self.case_pool.registrations.get(author)
            ]
            if not contributions:
                return
            bind = self.session.get_bind()
            with Session(bind=getattr(bind, "engine", bind)) as session, session.begin():
                # 正式事务已经提交后仅内存确认失败时，不得把已采用交付改写为空登记
                if session.scalar(select(DiagnosisReport.report_id).where(
                    DiagnosisReport.session_id == self.execution_id,
                )) is not None:
                    return
                for contribution in contributions:
                    warnings = self.case_pool.save_work(session, contribution)
                    if warnings:
                        raise RuntimeError(f"诊断失败案例未完整保存: {warnings}")

    def freeze_identity(self) -> None:
        if snapshot_digest(self.draft._declarations()) != self.source_hash:
            raise ValueError("原始声明清单改变，禁止发布")
        try:
            self.draft.freeze_identity()
        except ValueError as exc:
            self._correct("identity", exc)

    def freeze_structure(self) -> None:
        try:
            self.draft.freeze_structure()
            return
        except ValueError as exc:
            # 2026-10-15 结构独立 work 已删，缺失或失版结构比较归属各自事件责任工作修改
            events = sorted(self.draft.events)
            required = {(source, target) for index, source in enumerate(events) for target in events[index + 1 :]}
            affected = {
                self.draft.events[source].source_work_id
                for pair in required - set(self.draft.structure_reviews)
                for source in pair
            } | {
                review.source_work_id
                for pair, review in self.draft.structure_reviews.items()
                if review.snapshot_hash != self.draft.pair_snapshot(*pair)
            }
            if not affected:
                self._correct("structure", exc)
                return
            error = ValueError("事件结构比较清单未完整处置") if required - set(self.draft.structure_reviews) else exc
            error.diagnosis_phase = "structure"  # type: ignore[attr-defined]
            raise DiagnosisWorkCorrections(
                tuple(sorted(affected)),
                {
                    "field": "structure",
                    "actual": str(error),
                    "expected": "依据真实来源显式修正自己提交的相冲突候选；不得改动其他 work 的已接受声明",
                },
            ) from error

    def _narrative_snapshot(self) -> str:
        return snapshot_digest(
            {
                "identity": self.draft.identity_snapshot,
                "structure": self.draft.structure_snapshot,
                **{
                    name: record_payloads(getattr(self.draft, name).values())
                    for name in ("arcs", "event_arc_links", "outcomes", "event_outcome_links", "conflicts")
                },
            }
        )

    def finishing_work(self) -> list[WorkSpec]:
        """2026-10-15 用户裁定「收尾是一个 agent 会话完成叙事+报告」：叙事打包与报告
        派发全部并入一个收尾报告工作"""
        events = [item.model_dump(mode="json") for item in self.draft.events.values()]
        report_material = {
            "structure_snapshot": self.draft.structure_snapshot,
            "catalog": [{key: row[key] for key in ("event_id", "title", "problem", "status")} for row in events],
            "arcs": [{"arc_id": item.arc_id, "title": item.title} for item in self.draft.arcs.values()],
            "outcomes": [{"outcome_id": item.outcome_id, "title": item.title}
                         for item in self.draft.outcomes.values()],
        }
        report = WorkSpec(
            self.run_id,
            "report",
            tuple(row["event_id"] for row in events),
            report_material,
        )
        self.work[report.work_id] = report
        return [report]

    def publish(self) -> AgentAnalysis:
        reports = [(key, data["analysis"]) for key, data in self.reports.items() if "analysis" in data]
        if len(reports) != 1:
            raise ValueError("正式发布必须有一个真实报告写入者")
        work_id, payload = reports[0]
        if self.report_bindings[work_id] != self._narrative_snapshot():
            raise ValueError("最终报告快照已失效")
        organization = self.draft.finish()
        analysis = AgentAnalysis.model_validate(
            {
                **payload,
                "novel_id": self.novel_id,
                "foreshadow_expectation": DiagnosisQueries(self.session).calculate_foreshadow_expectation(
                    self.run_id,
                    declaration_bindings={declaration: event.event_id for event in self.draft.events.values()
                                          for declaration in event.declaration_ids},
                ),
                "narrative_organization": organization.model_dump(mode="json"),
            }
        )
        save_diagnosis_result(
            self.session,
            self.run_id,
            analysis,
            case_pool=self.case_pool,
            case_graph=self._case_graph(),
            case_writers=self.case_writers,
            case_candidates=self._case_dialogue_candidates(),
        )
        return analysis


def create_diagnosis_domain(
    *, session: Session, run_id: str, novel_id: str, execution_id: str, novel_title: str | None = None
) -> DiagnosisDomain:
    """2026-10-15 用户裁定「不要context_window_tokens」「不要预算，要切分」：诊断只解析
    diagnosis_model_id 对应的池条目并要求其存在（model_id 仅作审计/计数标识），
    不读取任何窗口或容量数字。"""
    from src.config import settings

    model_id = settings.models.diagnosis_model_id
    entry = next(
        (item for item in settings.models.model_pool if item.model_id == model_id), None
    )
    if model_id is None or entry is None:
        raise ValueError("诊断模型不在模型池中")
    return DiagnosisDomain(
        session=session,
        run_id=run_id,
        novel_id=novel_id,
        execution_id=execution_id,
        novel_title=novel_title,
        model_id=entry.model_id,
    )
