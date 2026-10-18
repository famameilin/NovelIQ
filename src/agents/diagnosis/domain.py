"""诊断工作的领域权限、候选贡献和一次发布，不调用协调模型"""

from __future__ import annotations

import json
import threading
from typing import Any, cast

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

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
    snapshot_digest,
)
from src.storage import Storage
from src.utils.identity import stable_digest

from .evidence import DiagnosisEvidenceLedger
from .persistence import save_diagnosis_result
from .program_runtime import DiagnosisProgramRuntime
from .prompts import build_diagnosis_system_prompt
from .tools import build_diagnosis_tools
from .work_runtime import CaseUnit, DiagnosisWorkContext, DiagnosisWorkCorrections, WorkPhase

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
    """候选在草稿内的稳定记录键（各组的真实身份键或规范化端点对）"""
    if group == "structure_reviews":
        return tuple(sorted((item.source_event_id, item.target_event_id)))
    if group == "containments":
        return (item.parent_event_id, item.child_event_id)
    if group == "event_arc_links":
        return (item.event_id, item.arc_id)
    if group == "event_outcome_links":
        return (item.event_id, item.outcome_id)
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
    """每次原语调用绑定实际案例，异步读取不会串改其他会话的写入来源"""

    def __init__(self, domain: DiagnosisDomain, unit: CaseUnit, invocation: str) -> None:
        self.domain, self.unit, self.invocation = (domain, unit, invocation)

    def __getattr__(self, name: str) -> Any:
        draft = self.domain.draft
        value = getattr(draft, name)
        if not callable(value):
            return value

        def invoke(*args: Any, **kwargs: Any) -> Any:
            draft.case_id, draft.producer_invocation_id = (self.unit.case_id, self.invocation)
            identity_ops = {"identity", "review_declarations", "compare_declarations"}
            structure_ops = {"event", "contain", "relate_events", "review_events", "structure_review"}
            narrative_ops = {"register_arc", "link_event_arc", "register_outcome", "link_event_outcome"}
            draft.responsible_ids = set(self.unit.responsible_ids) if self.unit.role == "case" else None
            if name in identity_ops and self.unit.role != "case":
                raise ValueError("只有案例 Agent 可以提交身份、事实核对或来源比较")
            if name in structure_ops and self.unit.role != "case":
                raise ValueError("只有案例 Agent 可以提交事件结构写入")
            if name in narrative_ops and self.unit.role != "report":
                raise ValueError("叙事写入只能由报告 Agent 完成")
            if name == "structure_review":
                pair = tuple(sorted((kwargs["source_event_id"], kwargs["target_event_id"])))
                if pair not in self.domain._structure_pairs(self.unit):
                    raise ValueError("结构比较不属于本案例的已派发事项")
            if name in {"contain", "relate_events"}:
                source = kwargs["parent_event_id"] if name == "contain" else kwargs["source_id"]
                target = kwargs["child_event_id"] if name == "contain" else kwargs["target_id"]
                pair = (min(source, target), max(source, target))
                owned_new = any(
                    self.domain.draft.events[key].source_case_id == self.unit.case_id
                    and (not self.domain.draft.events[key].declaration_ids)
                    for key in (source, target)
                    if key in self.domain.draft.events
                )
                if pair not in self.domain._structure_pairs(self.unit) and (not owned_new):
                    raise ValueError("结构写入端点不是本案例的已派发事项或本案例新建父事件")
            if name == "review_events":
                allowed = {key for pair in self.domain._structure_pairs(self.unit) for key in pair}
                allowed.update(
                    item.event_id for item in draft.events.values() if item.source_case_id == self.unit.case_id
                )
                allowed.update(self.domain._written_structure_endpoints(self.unit))
                if not set(args[0] if args else kwargs["event_ids"]) <= allowed:
                    raise ValueError("事件核对端点不是本案例的责任范围")
            return value(*args, **kwargs)

        def locked_invoke(*args: Any, **kwargs: Any) -> Any:
            with self.domain.lock:
                return invoke(*args, **kwargs)

        return locked_invoke


class DiagnosisDomain:
    """冻结真实章级来源，案例只保存自己产生的候选，最终同一事务发布"""

    def __init__(
        self, *, session: Storage, run_id: str, novel_id: str, execution_id: str, novel_title: str | None, model_id: str
    ) -> None:
        self.session, self.run_id, self.novel_id, self.execution_id = (session, run_id, novel_id, execution_id)
        self.novel_title, self.model_id = (novel_title, model_id)
        self.lock = threading.RLock()
        self.read_sessions: dict[str, Storage] = {}
        self.draft = EventOrganizationDraft(session, run_id, execution_id)
        self.sources = self.draft._declarations()
        self.source_hash = snapshot_digest(self.sources)
        self.case_pool = CasePool(run_id)
        self.case_pool.load_storage(session)
        self.reports: dict[str, dict[str, Any]] = {}
        self.ledgers: dict[str, DiagnosisEvidenceLedger] = {}
        self.case_writers: dict[str, Any] = {}
        self._case_graph_value: Any | None = None
        self._case_dialogue_value: list[Any] | None = None
        self.units: dict[str, CaseUnit] = {}
        self.report_bindings: dict[str, str] = {}
        self.initial: list[CaseUnit] | None = None
        self.session.diagnosis.register_session(run_id=run_id, session_id=execution_id)

    def register_session_identity(self) -> None:
        """派发前先短事务登记整轮会话身份：执行事实引用会话前会话必须已存在

        案例执行行由审计记录器在派发时创建并直接携带归属（run/角色/案例锚）。
        """
        self.session.diagnosis.register_session(run_id=self.run_id, session_id=self.execution_id)

    def next_dispatch_attempt(self, case_id: str) -> int:
        """本轮派发的真实尝试序号：该案例既有执行事实数 + 1（跨轮累计，不重置）

        登记契约要求 (run, 案例, 角色, attempt) 唯一（"该次尝试已有真实执行"）；
        续跑重派是新的真实尝试，必须推进序号才能登记自己的执行事实（2026-10-17 run 52cbb1ac）。
        """
        unit = self.units.get(case_id)
        role = "case" if unit is not None and unit.role == "case" else "report"
        return self.session.diagnosis.next_attempt(self.run_id, role, case_id if role == "case" else None)

    def _register_attempt(self, unit: CaseUnit, invocation: str, attempt_number: int) -> None:
        """每次真实尝试先短事务登记会话与执行事实，审计与产物都引用同一身份"""
        self.session.diagnosis.register_attempt(
            run_id=self.run_id,
            session_id=self.execution_id,
            execution_id=invocation,
            role=unit.role,
            case_anchor=unit.case_id if unit.role == "case" else None,
            attempt_number=attempt_number,
        )

    def _declaration_positions(self) -> dict[str, int]:
        """声明按真实来源章序与段序的稳定顺序，比较配对的迟早由它裁定"""
        return {identifier: position for position, identifier in enumerate(self.sources)}

    def _work_messages(self, role: str, responsible: tuple[str, ...], material: dict[str, Any]) -> list[Any]:
        """规划和发起请求使用完全相同的消息封装"""
        return [
            SystemMessage(content=build_diagnosis_system_prompt(self.novel_title, role)),
            HumanMessage(
                content=json.dumps(
                    {"role": role, "responsible_ids": responsible, "materials": material}, ensure_ascii=False
                )
            ),
        ]

    def initial_work(self) -> list[CaseUnit]:
        """2026-10-15 用户裁定「建一个事件进一个池」「切分不要使用max_tokens」：切分只保留
        事件边界，每个声明一个案例单元，payload 精简为 {source_hash, event_ids}"""
        if self.initial is not None:
            return self.initial
        self.initial = [
            CaseUnit(
                next(
                    (
                        identifier
                        for identifier, record in self.case_pool.cases.items()
                        if record.get("automatic") and (record.get("payload") or {}).get("event_id") == declaration_id
                    )
                ),
                "case",
                (declaration_id,),
                {"source_hash": self.source_hash, "event_ids": [declaration_id]},
            )
            for declaration_id in self.sources
        ]
        self.units.update({item.case_id: item for item in self.initial})
        return self.initial

    def _comparison_receipts(self, responsible: tuple[str, ...]) -> list[dict[str, Any]]:
        """交接是有来源的判断索引，原理由和原文仍留在比较候选与声明读取面"""
        return [
            {
                "source_declaration_id": source,
                "target_declaration_id": target,
                "disposition": item.disposition,
                "source_case_id": item.source_case_id,
                "producer_invocation_id": item.producer_invocation_id,
            }
            for (source, target), item in self.draft.declaration_comparisons.items()
            if source in responsible or target in responsible
        ]

    def clear_case_candidates(self, case_id: str) -> None:
        """修正重派从零会话开始，程序侧清退本案例旧候选，旧判断只在审计保留"""
        with self.lock:
            for group in _GROUPS:
                target = getattr(self.draft, group)
                for key in [key for key, item in target.items() if item.source_case_id == case_id]:
                    del target[key]
            for key in [key for key, item in self.draft.revisions.items() if item.source_case_id == case_id]:
                del self.draft.revisions[key]
            self.reports.pop(case_id, None)
            self.ledgers.pop(case_id, None)

    def _identity_gaps(self, unit: CaseUnit) -> list[str]:
        """一次列全身份段缺口；逐条 raise 会让模型每回合只补一条，预算在补齐途中耗尽
        （run 52cbb1ac 第 9 轮：案例 68fb7951 第 9 回合 finish 只报一条比较缺口，
        第 10 回合补完该条后又被下一条挡住，触顶失败）"""
        position = self._declaration_positions()
        gaps: list[str] = []
        for source in unit.responsible_ids:
            missing = [
                target
                for target in position
                if position[target] > position.get(source, -1)
                and (source, target) not in self.draft.declaration_comparisons
            ]
            if missing:
                gaps.append(f"来源比较尚未明确判断: source={source} targets={missing}")
        for identifier in unit.responsible_ids:
            if identifier not in self.draft.declaration_reviews:
                gaps.append(f"声明缺少事实核对: declaration_id={identifier}")
            if any(identifier in item.declaration_ids for item in self.draft.events.values()):
                continue
            if not any(
                (
                    target == identifier and item.disposition == "same_event"
                    for (_, target), item in self.draft.declaration_comparisons.items()
                )
            ):
                gaps.append(f"声明缺少身份判断或带证据的交接: declaration_id={identifier}")
        return gaps

    def _structure_pairs(self, unit: CaseUnit) -> set[tuple[str, str]]:
        events = sorted(
            (item for item in self.draft.events.values() if item.declaration_ids),
            key=lambda item: (item.first_text_position, item.event_id),
        )
        return {
            (min(source.event_id, target.event_id), max(source.event_id, target.event_id))
            for index, source in enumerate(events)
            if source.source_case_id == unit.case_id
            for target in events[index + 1 :]
        }

    def _written_structure_endpoints(self, unit: CaseUnit) -> set[str]:
        return {
            key
            for edge in self.draft.containments.values()
            if edge.source_case_id == unit.case_id
            for key in (edge.parent_event_id, edge.child_event_id)
        } | {
            key
            for edge in self.draft.relations.values()
            if edge.source_case_id == unit.case_id
            for key in (edge.source_id, edge.target_id)
        }

    def _structure_gaps(self, unit: CaseUnit) -> list[str]:
        """一次列全结构段缺口，理由与身份段相同：拒收回执必须覆盖当前全部未满足义务"""
        produced = [item for item in self.draft.events.values() if item.source_case_id == unit.case_id]
        checked = {item.event_id for item in produced} | self._written_structure_endpoints(unit)
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
            for pair in sorted(self._structure_pairs(unit))
            if self.draft.structure_reviews.get(pair) is None
            or self.draft.structure_reviews[pair].source_case_id != unit.case_id
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

    def _case_source_chapter(self, unit: CaseUnit) -> int:
        """案例写入的归属章=责任声明所在章；报告案例与无来源情形归第一章"""
        for identifier in unit.responsible_ids:
            declaration = self.sources.get(identifier)
            if declaration is not None and declaration.get("chapter_id") is not None:
                return int(declaration["chapter_id"])
        for position in sorted(self.sources.values(), key=lambda row: row.get("chapter_order") or 0):
            if position.get("chapter_id") is not None:
                return int(position["chapter_id"])
        return 0

    def build_context(
        self, unit: CaseUnit, phase: WorkPhase, observer: Any, corrections: dict[str, Any] | None
    ) -> DiagnosisWorkContext:
        with self.lock:
            if corrections is not None:
                self.clear_case_candidates(unit.case_id)
            return self._build_context_locked(unit, phase, observer, corrections)

    def _build_context_locked(
        self, unit: CaseUnit, phase: WorkPhase, observer: Any, corrections: dict[str, Any] | None
    ) -> DiagnosisWorkContext:
        invocation = str(getattr(observer, "invocation_id", None) or self.session.new_id())
        context = getattr(observer, "_context", None)
        attempt_number = 1
        if isinstance(context, dict):
            invocation = str(context.get("execution_id") or invocation)
            attempt_number = int(context.get("attempt_number") or 1)
        self._register_attempt(unit, invocation, attempt_number)
        ledger = self.ledgers.setdefault(unit.case_id, DiagnosisEvidenceLedger())
        report = self.reports.setdefault(unit.case_id, {})
        proxy = _WorkDraft(self, unit, invocation)
        if unit.case_id not in self.read_sessions:
            self.read_sessions[unit.case_id] = self.session
        tools = build_diagnosis_tools(
            self.read_sessions[unit.case_id],
            self.run_id,
            evidence_ledger=ledger,
            organization_draft=cast(EventOrganizationDraft, proxy),
            report_draft=report,
            case_pool=self.case_pool,
            execution_id=self.execution_id,
            case_writes_graph=self._case_graph(),
            case_source_chapter=self._case_source_chapter(unit),
            case_dialogue_candidates=self._case_dialogue_candidates(),
            case_writer_store=self.case_writers,
            case_id=unit.case_id,
            producer_invocation_id=invocation,
        )
        for tool in tools:
            if tool.name != "write_diagnosis":
                continue
            original = tool.func

            def write_report(*args: Any, _original: Any = original, **kwargs: Any) -> Any:
                if unit.role != "report":
                    raise ValueError("本案例没有全书报告提交责任")
                result = _original(*args, **kwargs)
                self.report_bindings[unit.case_id] = self._narrative_snapshot()
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
        material: dict[str, Any] = dict(unit.input_payload)
        if phase == "structure":
            material = {**material, "identity_snapshot": self.draft.identity_snapshot}
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
        if unit.role == "case" and phase == "identity":
            receipts = self._comparison_receipts(unit.responsible_ids)
            if receipts:
                material["comparisons"] = receipts
        if corrections is not None:
            material["corrections"] = corrections

        def complete() -> list[str]:
            if phase == "identity":
                return self._identity_gaps(unit)
            if phase == "structure":
                return self._structure_gaps(unit)
            try:
                ledger.require_evidence()
                analysis = AgentAnalysis.model_validate(report.get("analysis", {}))
                expected = {
                    int(row["topic_id"]) for row in DiagnosisQueries(self.session).fetch_topic_words(self.run_id)
                }
                if {int(key) for key in analysis.topic_labels} != expected:
                    raise ValueError("报告主题键必须与真实主题数据完全一致")
                if self.report_bindings.get(unit.case_id) != self._narrative_snapshot():
                    raise ValueError("报告绑定的叙事快照已改变，须明确核对后重新提交报告")
            except ValueError as exc:
                return [str(exc)]
            return []

        messages = self._work_messages(unit.role, unit.responsible_ids, material)
        return DiagnosisWorkContext(program, messages, lambda: self._complete_locked(complete))

    def _complete_locked(self, check: Any) -> list[str]:
        with self.lock:
            return check()

    def close(self) -> None:
        """关闭每份工作独立的取证会话，不提交任何领域事务"""
        with self.lock:
            self.read_sessions.clear()

    def _correct(self, phase: str, error: ValueError) -> None:
        error.diagnosis_phase = phase  # type: ignore[attr-defined]
        affected = tuple(getattr(error, "case_ids", ()))
        if not affected:
            raise error
        raise DiagnosisWorkCorrections(
            affected,
            {
                "field": phase,
                "actual": str(error),
                "expected": "依据真实来源显式修正自己提交的相冲突候选；不得改动其他案例的已接受声明",
            },
        ) from error

    def _register_unresolved_cases(self, error: BaseException) -> None:
        """只在最终失败时为仍在异常链上的冲突登记模板案例，来源候选保持原样"""
        seen: set[int] = set()
        current: BaseException | None = error
        conflicts: list[tuple[str, set[str]]] = []
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            affected = set(getattr(current, "case_ids", ()))
            phase = getattr(current, "diagnosis_phase", None)
            if affected and phase:
                conflicts.append((str(phase), affected))
            current = current.__cause__ or current.__context__
        if not conflicts:
            return
        author = self.execution_id
        self.case_pool.begin(author)
        for phase, affected in conflicts:
            for item in self.draft.events.values():
                if item.source_case_id not in affected:
                    continue
                paragraphs = sorted({ref.paragraph_id for ref in item.evidence})
                for paragraph_id in paragraphs:
                    prefix = f"{item.event_id}|event|{phase}_conflict|段{paragraph_id}|名"
                    width = 100 - len(prefix) - 18
                    if width <= 0:
                        raise ValueError("未决案例来源标识超出描述约束，不能截断事实")
                    chunks = [item.title[index : index + width] for index in range(0, len(item.title), width)]
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

        from src.case_pool.contributions import CaseContribution

        with self.lock:
            self._register_unresolved_cases(error)
            contributions = [
                CaseContribution(
                    self.run_id,
                    author,
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
            from src.storage.records.cases import CaseSave

            self.session.diagnosis.retain_pending(
                self.run_id,
                self.execution_id,
                tuple(CaseSave(item.run_id, item.author, item.snapshot_json) for item in contributions),
            )

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
            events = sorted(self.draft.events)
            required = {(source, target) for index, source in enumerate(events) for target in events[index + 1 :]}
            affected = {
                self.draft.events[source].source_case_id
                for pair in required - set(self.draft.structure_reviews)
                for source in pair
            } | {
                review.source_case_id
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
                    "expected": "依据真实来源显式修正自己提交的相冲突候选；不得改动其他案例的已接受声明",
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

    def finishing_work(self) -> list[CaseUnit]:
        """2026-10-15 用户裁定「收尾是一个 agent 会话完成叙事+报告」：叙事打包与报告
        派发全部并入一个报告案例单元"""
        events = [item.model_dump(mode="json") for item in self.draft.events.values()]
        report_material = {
            "structure_snapshot": self.draft.structure_snapshot,
            "catalog": [{key: row[key] for key in ("event_id", "title", "problem", "status")} for row in events],
            "arcs": [{"arc_id": item.arc_id, "title": item.title} for item in self.draft.arcs.values()],
            "outcomes": [{"outcome_id": item.outcome_id, "title": item.title} for item in self.draft.outcomes.values()],
        }
        report = CaseUnit(
            stable_digest(self.run_id, "diagnosis_report"),
            "report",
            tuple(row["event_id"] for row in events),
            report_material,
        )
        self.units[report.case_id] = report
        return [report]

    def publish(self) -> AgentAnalysis:
        reports = [(key, data["analysis"]) for key, data in self.reports.items() if "analysis" in data]
        if len(reports) != 1:
            raise ValueError("正式发布必须有一个真实报告写入者")
        case_id, payload = reports[0]
        if self.report_bindings[case_id] != self._narrative_snapshot():
            raise ValueError("最终报告快照已失效")
        organization = self.draft.finish()
        analysis = AgentAnalysis.model_validate(
            {
                **payload,
                "novel_id": self.novel_id,
                "foreshadow_expectation": DiagnosisQueries(self.session).calculate_foreshadow_expectation(
                    self.run_id,
                    declaration_bindings={
                        declaration: event.event_id
                        for event in self.draft.events.values()
                        for declaration in event.declaration_ids
                    },
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
    *, session: Storage, run_id: str, novel_id: str, execution_id: str, novel_title: str | None = None
) -> DiagnosisDomain:
    """2026-10-15 用户裁定「不要context_window_tokens」「不要预算，要切分」：诊断只解析
    diagnosis_model_id 对应的池条目并要求其存在（model_id 仅作审计/计数标识），
    不读取任何窗口或容量数字。"""
    from src.config import settings

    model_id = settings.models.diagnosis_model_id
    entry = next((item for item in settings.models.model_pool if item.model_id == model_id), None)
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
