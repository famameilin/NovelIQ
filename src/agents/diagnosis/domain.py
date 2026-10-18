"""诊断领域：会话上下文（工具与材料）、案例写入绑定、会话保存与报告结果

案例会话自取未承诺案例：search_cases 取未解决、promise_case 接手，随后直接调用
写入工具完成案例；写入必须显式携带 caseid，per-call 绑定来源与案例账本。
每个会话做完自行保存一次：案例会话存案例产物，报告会话存叙事组织与全书报告。
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from src.case_pool import CasePool
from src.diagnosis.queries import DiagnosisQueries
from src.diagnosis.schema import AgentAnalysis
from src.event_trees.diagnosis_persistence import hydrate_draft_from_run
from src.event_trees.organization import (
    EventOrganizationDraft,
    record_payloads,
    snapshot_digest,
)
from src.storage import Storage, new_id
from src.utils.identity import stable_digest

from .evidence import DiagnosisEvidenceLedger
from .persistence import save_diagnosis_result
from .program_runtime import DiagnosisProgramRuntime
from .prompts import build_diagnosis_system_prompt
from .tools import build_diagnosis_tools
from .work_runtime import CASE_SESSION_MAX_ROUNDS, DiagnosisWorkContext


class CaseWriteBinding:
    """案例写入绑定：按本次调用 caseid 选择来源与账本；写入必须显式带 caseid

    工具在执行前调用 select（bind_caseid 的 prepare），随后业务体与关联层沿用本次
    选择的来源；账本代理把 write_entity/write_relation/write_dialogue 的调用转发到
    所办案例自己的账本。
    """

    def __init__(self, resolve: Callable[[str], tuple[Any, str]], draft: EventOrganizationDraft) -> None:
        self._resolve = resolve
        self._draft = draft
        self._active: tuple[Any, str] | None = None

    def select(self, caseid: Any) -> None:
        if not isinstance(caseid, str) or not caseid:
            raise ValueError(
                "本次写入缺少 caseid：请填所办案例的真实 ID（search_cases 取未解决案例，"
                "promise_case 接手后带回执中的 case_id）"
            )
        writer, invocation = self._resolve(caseid)
        self._draft.case_id, self._draft.producer_invocation_id = caseid, invocation
        self._active = (writer, invocation)

    def writer(self) -> tuple[Any, str]:
        if self._active is None:
            raise ValueError("案例处置写入必须显式提供所办案例的 caseid")
        return self._active

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return getattr(self.writer()[0], name)


class DiagnosisDomain:
    """案例会话自取办理、做完即存；全部结束后报告会话收尾并保存"""

    def __init__(
        self,
        *,
        session: Storage,
        run_id: str,
        novel_id: str,
        execution_id: str,
        novel_title: str | None,
        model_id: str,
    ) -> None:
        self.session, self.run_id, self.novel_id, self.execution_id = session, run_id, novel_id, execution_id
        self.novel_title, self.model_id = novel_title, model_id
        self.lock = threading.RLock()
        self.read_sessions: dict[str, Storage] = {}
        self.ledgers: dict[str, DiagnosisEvidenceLedger] = {}
        self.draft = EventOrganizationDraft(session, run_id, execution_id)
        self.sources = self.draft._declarations()
        self.source_hash = snapshot_digest(self.sources)
        self.case_pool = CasePool(run_id)
        self.case_pool.load_storage(session)
        # 续跑：把会话保存（每会话做完保存一次）留下的组织行水合进内存后继续
        hydrate_draft_from_run(session, run_id, self.draft)
        self.session_saved: set[str] = set()
        self._analysis: AgentAnalysis | None = None
        self.reports: dict[str, dict[str, Any]] = {}
        self.report_anchor = stable_digest(run_id, "diagnosis_report")
        self.report_bindings: dict[str, str] = {}
        # 三类案例处置写入承接（复用标注语义写入面），按案例缓存账本
        self.case_writers: dict[str, Any] = {}
        self._case_executions: dict[str, str] = {}
        self._case_graph_value: Any | None = None
        self._case_dialogue_value: list[Any] | None = None
        # 诊断整轮身份先短事务登记：失败轮次同样保留审计身份，不写任何 checkpoint
        self.register_session_identity()

    def register_session_identity(self) -> None:
        "登记整轮身份，连接与事务由 Storage 管理"
        self.session.diagnosis.register_session(run_id=self.run_id, session_id=self.execution_id)

    def save_session_progress(self, author: str, role: str) -> None:
        "会话产物冻结后交给 Storage 原子保存，提交完成后确认内存"
        from src.storage.records.cases import CaseSave
        from src.storage.records.diagnosis_save import DiagnosisSessionSave

        from .persistence import _save_case_writes

        with self.lock:
            if author in self.session_saved:
                return
            if role == "report":
                self._save_report_progress(author)
                return
            cases = {key for key, runtime in self.case_pool.case_runtime.items() if runtime.get("owner") == author}
            writers = {key: value for key, value in self.case_writers.items() if key in cases}
            graph = self._case_graph()
            facts, updates = _save_case_writes(
                self.session, self.run_id, "", graph=graph, writers=writers, candidates=self._case_dialogue_candidates()
            )
            contribution = CaseSave(
                self.run_id,
                author,
                json.dumps(
                    {
                        "created_case_ids": sorted(self.case_pool.created.get(author, set())),
                        "registrations": {
                            key: self.case_pool.cases[key]
                            for key in sorted(self.case_pool.registrations.get(author, set()))
                        },
                        "deliveries": self.case_pool.deliveries.get(author, []),
                    },
                    ensure_ascii=False,
                ),
            )
            organization = {
                name: {
                    str(index): item.model_dump(mode="json")
                    for index, item in enumerate(getattr(self.draft, name).values())
                }
                for name in (
                    "events",
                    "containments",
                    "relations",
                    "reviewed_events",
                    "declaration_reviews",
                    "declaration_comparisons",
                    "structure_reviews",
                )
            }
            self.session.diagnosis.save_session(
                DiagnosisSessionSave(
                    self.run_id,
                    author,
                    frozenset(cases),
                    json.dumps(organization, ensure_ascii=False),
                    frozenset(self.sources),
                    tuple(self._case_executions[key] for key in sorted(cases) if key in self._case_executions),
                    facts,
                    updates,
                    (contribution,),
                )
            )
            self.case_pool.confirm(author)
            for key, (_writer, invocation) in writers.items():
                graph.confirm(invocation)
                self.case_writers.pop(key, None)
            self.session_saved.add(author)

    def _save_report_progress(self, author: str) -> None:
        """报告会话收尾保存：快照校验、叙事组织与全书报告同一事务入库

        报告写入时绑定叙事快照，保存时快照必须仍然一致；报告未提交即本轮失败。
        案例交付与正式报告绑定走既有保存链，重投只核验不改写已保存结果。
        """
        reports = [(anchor, data["analysis"]) for anchor, data in self.reports.items() if "analysis" in data]
        if len(reports) != 1:
            raise ValueError("报告会话结束但没有提交报告：write_diagnosis 必须提交且只能提交一次")
        anchor, payload = reports[0]
        if self.report_bindings.get(anchor) != self._narrative_snapshot():
            raise ValueError("报告绑定的叙事快照已改变，禁止保存：报告提交后不得再改叙事组织")
        if snapshot_digest(self.draft._declarations()) != self.source_hash:
            raise ValueError("原始声明清单已改变，禁止保存")
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
        self._analysis = analysis
        self.session_saved.add(author)

    def analysis_result(self) -> AgentAnalysis:
        """报告会话保存后的正式诊断结果；未保存即不可读"""
        if self._analysis is None:
            raise RuntimeError("诊断报告尚未保存")
        return self._analysis

    def _ensure_case_execution(self, caseid: str) -> str:
        "登记案例真实尝试，身份由 Storage 分配"
        existing = self._case_executions.get(caseid)
        if existing is not None:
            return existing
        attempt_number = self.session.diagnosis.next_attempt(self.run_id, "case", caseid)
        execution_id = new_id()
        from src.storage.records.cases import CaseSave

        registration = CaseSave(
            self.run_id,
            self.execution_id,
            json.dumps(
                {
                    "created_case_ids": [caseid],
                    "registrations": {caseid: self.case_pool.cases[caseid]},
                    "deliveries": [],
                },
                ensure_ascii=False,
            ),
        )
        self.session.diagnosis.register_attempt(
            run_id=self.run_id,
            session_id=self.execution_id,
            execution_id=execution_id,
            role="case",
            attempt_number=attempt_number,
            case_anchor=caseid,
            case_registration=registration,
        )
        self._case_executions[caseid] = execution_id
        return execution_id

    def _resolve_case(self, author: str, caseid: str) -> tuple[Any, str]:
        """案例写入来源：必须是本会话已承诺的案例（接手即承诺，先承诺后写入）"""
        if caseid not in self.case_pool.cases:
            raise ValueError(f"caseid={caseid!r} 不属于当前 run 的案例池；请取 search_cases 返回的真实 ID")
        runtime = self.case_pool.case_runtime.get(caseid) or {}
        if not runtime.get("promised"):
            raise ValueError("该案例尚未 promise：先 promise_case(case_id=...) 接手，再调用写入完成它")
        owner = runtime.get("owner")
        if owner is not None and owner != author:
            raise ValueError("该案例已由其他执行承诺；请改取其他未承诺案例")
        invocation = self._ensure_case_execution(caseid)
        return self._case_writer(caseid, invocation), invocation

    def _case_chapter(self, caseid: str) -> int:
        "按案例来源章定位写入范围，缺省使用运行内首章"
        case = self.case_pool.cases.get(caseid) or {}
        chapter = (case.get("payload") or {}).get("chapter_id")
        if chapter is not None:
            return int(chapter)
        rows = self.session.chapters.fetch_chapter_texts(self.run_id)
        return min((int(chapter_id) for chapter_id, _text in rows), default=0)

    def _case_writer(self, caseid: str, invocation: str) -> Any:
        """案例处置账本：按案例惰性建立（标注语义写入原形，阶段=诊断）

        返回所办案例自己的账本；case_writers 里存 (账本, 执行身份) 供报告保存折入。
        """
        existing = self.case_writers.get(caseid)
        if existing is not None:
            return existing[0]
        from src.agents.annotation.ledger import AnnotationToolLedger

        chapter = self._case_chapter(caseid)
        ledger = AnnotationToolLedger(
            run_scope=self.run_id,
            current_chapter_id=chapter,
            current_chapter_text="",
            allow_future_context=False,
        )
        ledger.phase = "diagnosis_open"
        ledger.graph = self._case_graph()
        ledger.dialogue.dialogue_candidates = self._case_dialogue_candidates()
        ledger.graph.begin(invocation, chapter, "case")
        self.case_writers[caseid] = (ledger, invocation)
        return ledger

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

    def _case_view(self, case: dict[str, Any]) -> dict[str, Any]:
        """对话案例补充全书候选序号，供 write_dialogue(candidate_index=...) 直接判定"""
        if case.get("case_type") != "dialogue":
            return case
        candidate_key = str((case.get("payload") or {}).get("candidate_key") or "")
        index = next(
            (
                position + 1
                for position, candidate in enumerate(self._case_dialogue_candidates())
                if candidate.candidate_key == candidate_key
            ),
            None,
        )
        return {**case, "dialogue_index": index} if index is not None else case

    def _unresolved_totals(self) -> dict[str, int]:
        """会话起始只见未承诺案例计数：案例清单由会话自行 search 取"""
        totals: dict[str, int] = {}
        for case in self.case_pool.search():
            if not case["promised"]:
                totals[str(case["case_type"])] = totals.get(str(case["case_type"]), 0) + 1
        return totals

    def _session_messages(self, role: str, material: dict[str, Any]) -> list[Any]:
        return [
            SystemMessage(content=build_diagnosis_system_prompt(self.novel_title, role)),
            HumanMessage(content=json.dumps({"role": role, "materials": material}, ensure_ascii=False)),
        ]

    def build_session_context(self, role: str, execution_id: str, observer: Any) -> DiagnosisWorkContext:
        with self.lock:
            return self._build_session_context_locked(role, execution_id, observer)

    def _build_session_context_locked(self, role: str, invocation: str, observer: Any) -> DiagnosisWorkContext:
        from src.config import settings

        ledger = DiagnosisEvidenceLedger()
        self.ledgers[invocation] = ledger
        if invocation not in self.read_sessions:
            self.read_sessions[invocation] = self.session
        case_binding: CaseWriteBinding | None = None
        report: dict[str, Any] = {}
        if role == "report":
            self.reports[self.report_anchor] = report
            # 报告会话的叙事与报告写入以报告锚点为来源，随会话固定
            self.draft.case_id = self.report_anchor
            self.draft.producer_invocation_id = invocation
            events = [item.model_dump(mode="json") for item in self.draft.events.values()]
            material: dict[str, Any] = {
                "catalog": [{key: row[key] for key in ("event_id", "title", "problem", "status")} for row in events],
                "arcs": [{"arc_id": item.arc_id, "title": item.title} for item in self.draft.arcs.values()],
                "outcomes": [
                    {"outcome_id": item.outcome_id, "title": item.title} for item in self.draft.outcomes.values()
                ],
            }
        else:
            case_binding = CaseWriteBinding(
                resolve=lambda caseid: self._resolve_case(invocation, caseid), draft=self.draft
            )
            material = {"unresolved_case_totals": self._unresolved_totals()}
        tools = build_diagnosis_tools(
            self.read_sessions[invocation],
            self.run_id,
            role=role,
            evidence_ledger=ledger,
            organization_draft=self.draft,
            report_draft=report,
            case_pool=self.case_pool,
            execution_id=invocation,
            case_binding=case_binding,
            case_writes_graph=self._case_graph() if case_binding is not None else None,
            case_view=self._case_view if case_binding is not None else None,
        )
        for tool in tools:
            if tool.name != "write_diagnosis":
                continue
            original = tool.func

            def write_report(*args: Any, _original: Any = original, **kwargs: Any) -> Any:
                result = _original(*args, **kwargs)
                self.report_bindings[self.report_anchor] = self._narrative_snapshot()
                return result

            tool.func = write_report
        for tool in tools:
            original_function = tool.func
            if original_function is not None:

                def locked_tool(*args: Any, _function: Any = original_function, **kwargs: Any) -> Any:
                    with self.lock:
                        return _function(*args, **kwargs)

                tool.func = locked_tool
        program = DiagnosisProgramRuntime(
            tools,
            observer=observer,
            invocation_id=invocation,
            dialogue_total=lambda: len(self._case_dialogue_candidates()),
        )

        def complete() -> list[str]:
            if role != "report":
                return []
            try:
                ledger.require_evidence()
                analysis = AgentAnalysis.model_validate(report.get("analysis", {}))
                expected = {
                    int(row["topic_id"]) for row in DiagnosisQueries(self.session).fetch_topic_words(self.run_id)
                }
                if {int(key) for key in analysis.topic_labels} != expected:
                    raise ValueError("报告主题键必须与真实主题数据完全一致")
                if self.report_bindings.get(self.report_anchor) != self._narrative_snapshot():
                    raise ValueError("报告绑定的叙事快照已改变，须明确核对后重新提交报告")
            except ValueError as exc:
                return [str(exc)]
            return []

        max_rounds = settings.models.diagnosis.max_iterations if role == "report" else CASE_SESSION_MAX_ROUNDS
        messages = self._session_messages(role, material)
        return DiagnosisWorkContext(program, messages, lambda: self._complete_locked(complete), max_rounds)

    def _complete_locked(self, check: Any) -> list[str]:
        with self.lock:
            return check()

    def close(self) -> None:
        "释放领域持有的无连接读取入口"
        with self.lock:
            self.read_sessions.clear()

    def retain_pending_cases(self, error: BaseException) -> None:
        """失败或取消只短事务保留登记，不采用交付、不重写已保存产物

        会话完成的保存已经落库、不再回退；未保存会话只保留案例登记（不落承诺与
        交付），其案例按未解决留给续跑的会话重办。
        """
        from src.case_pool.contributions import CaseContribution

        with self.lock:
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
            self.session.diagnosis.retain_pending(self.run_id, self.execution_id, tuple(contributions))

    def _narrative_snapshot(self) -> str:
        return snapshot_digest(
            {
                "identity": self.draft.identity_digest(),
                "structure": self.draft.structure_digest(),
                **{
                    name: record_payloads(getattr(self.draft, name).values())
                    for name in ("arcs", "event_arc_links", "outcomes", "event_outcome_links", "conflicts")
                },
            }
        )


def create_diagnosis_domain(
    *, session: Storage, run_id: str, novel_id: str, execution_id: str, novel_title: str | None = None
) -> DiagnosisDomain:
    """诊断只解析 diagnosis_model_id 对应的池条目并要求其存在（model_id 仅作审计/计数
    标识），不读取任何窗口或容量数字。"""
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
