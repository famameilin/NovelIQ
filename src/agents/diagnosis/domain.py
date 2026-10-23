"""诊断会话管理案例领取与提交、生产者写入与报告保存"""

from __future__ import annotations

import json
import time
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
from src.storage import Storage
from src.utils.identity import stable_digest

from .evidence import DiagnosisEvidenceLedger
from .persistence import save_diagnosis_result
from .program_runtime import DiagnosisProgramRuntime
from .prompts import build_diagnosis_system_prompt
from .read_context import DiagnosisGraphSource
from .tools import build_diagnosis_tools
from .work_runtime import DiagnosisWorkContext


class CaseWriteBinding:
    "案例写入前核验领取，账本与正式结果只归属真实生产者"

    def __init__(self, resolve: Callable[[str], tuple[Any, str]], draft: EventOrganizationDraft) -> None:
        self._resolve = resolve
        self._draft = draft
        self._active: tuple[Any, str] | None = None

    def select(self, caseid: Any) -> None:
        if not isinstance(caseid, str) or not caseid:
            raise ValueError(
                "本次写入缺少 caseid：请填所办案例的真实 ID（search_cases 取未解决案例，"
                "claim_case 接手后带回执中的 case_id）"
            )
        writer, invocation = self._resolve(caseid)
        self._draft.producer_agent_id = invocation
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
        agent_id: str,
        novel_title: str | None,
        model_id: str,
    ) -> None:
        self.session, self.run_id, self.novel_id, self.agent_id = session, run_id, novel_id, agent_id
        self.novel_title, self.model_id = novel_title, model_id
        self.read_sessions: dict[str, Storage] = {}
        self.ledgers: dict[str, DiagnosisEvidenceLedger] = {}
        self.draft = EventOrganizationDraft(session, run_id, agent_id)
        self.lock = self.draft.lock
        self.draft.cache_reads = True
        self.graph_sources: list[DiagnosisGraphSource] = []
        self.case_pool = CasePool(run_id)
        self.case_pool.load_storage(session)
        # 续跑：把会话保存（每会话做完保存一次）留下的组织行水合进内存后继续
        hydrate_draft_from_run(session, run_id, self.draft)
        self.session_saved: set[str] = set()
        self.case_sessions: set[str] = set()
        self._analysis: AgentAnalysis | None = None
        self.reports: dict[str, dict[str, Any]] = {}
        self.report_anchor = stable_digest(run_id, "diagnosis_report")
        self.report_bindings: dict[str, str] = {}
        # 三类案例处置写入承接（复用标注语义写入面），按生产者缓存账本
        self.case_writers: dict[str, Any] = {}
        self._case_graph_value: Any | None = None
        self._case_dialogue_value: list[Any] | None = None
        # 诊断整轮身份先短事务登记：失败轮次同样保留审计身份，不写任何 checkpoint

    def save_session_progress(self, author: str, role: str) -> None:
        "会话产物冻结后交给 Storage 原子保存，提交完成后确认内存"
        from src.storage.records.cases import CaseSave
        from src.storage.records.diagnosis_save import DiagnosisSessionSave

        from .persistence import _save_case_writes

        with self.draft.publication_lock:
            if author in self.session_saved:
                return
            if role == "report":
                self._save_report_progress(author)
                return
            with self.lock:
                writers = {key: value for key, value in self.case_writers.items() if key == author}
                graph = self._case_graph()
                facts, updates = _save_case_writes(
                    self.session, self.run_id, "", graph=graph, writers=writers,
                    candidates=self._case_dialogue_candidates(),
                )
                contribution = CaseSave(
                    self.run_id, author, json.dumps(self.case_pool.contribution(author), ensure_ascii=False),
                )
                organization = {
                    name: {
                        str(index): item.model_dump(mode="json")
                        for index, item in enumerate(getattr(self.draft, name).values())
                    }
                    for name in ("events", "containments", "relations", "reviewed_events", "structure_reviews")
                }
            saved = self.session.diagnosis.save_session(
                DiagnosisSessionSave(
                    self.run_id,
                    author,
                    json.dumps(organization, ensure_ascii=False),
                    facts,
                    updates,
                    (contribution,),
                )
            )
            with self.lock:
                self.case_pool.merge_committed(saved["committed_cases"])
                self.case_pool.confirm(author)
                for key, (_writer, invocation) in writers.items():
                    graph.confirm(invocation)
                    self.case_writers.pop(key, None)
                self.session_saved.add(author)
                self.draft.refresh_read_cache()
                for source in self.graph_sources:
                    source.refresh()

    def case_counts(self) -> tuple[int, int]:
        "案例池进度：(可领案例, 已提交案例)，仅有可领案例时派发"
        return self.case_pool.counts()

    def _save_report_progress(self, author: str) -> None:
        """报告会话收尾保存：快照校验、叙事组织与全书报告同一事务入库

        报告写入时绑定叙事快照，保存时快照必须仍然一致；报告未提交即本轮失败。
        案例交付与正式报告绑定走既有保存链，重投只核验不改写已保存结果。
        """
        self._require_cases_saved()
        reports = [(anchor, data["analysis"]) for anchor, data in self.reports.items() if "analysis" in data]
        self.draft.agent_id = author
        if not reports:
            raise ValueError("报告会话结束但没有提交报告：write_diagnosis 必须提交且只能提交一次")
        if len(reports) != 1:
            raise ValueError("报告会话结束但提交了多份报告：write_diagnosis 只能提交一次")
        anchor, payload = reports[0]
        if self.report_bindings.get(anchor) != self._narrative_snapshot():
            raise ValueError("报告绑定的叙事快照已改变，禁止保存：报告提交后不得再改叙事组织")
        organization = self.draft.finish()
        analysis = AgentAnalysis.model_validate(
            {
                **payload,
                "novel_id": self.novel_id,
                "foreshadow_expectation": DiagnosisQueries(self.session).calculate_foreshadow_expectation(
                    self.run_id,
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

    def _require_cases_saved(self) -> None:
        "报告只能读取已保存且没有待办的案例结果"
        if self.case_counts()[0]:
            raise ValueError("案例池仍有待领案例，禁止进入或发布报告")
        if self.case_pool.unsubmitted_for():
            raise ValueError("案例池仍有已领取但未提交案例，禁止进入或发布报告")
        if self.case_sessions - self.session_saved:
            raise ValueError("案例会话尚未全部保存，禁止进入或发布报告")

    def analysis_result(self) -> AgentAnalysis:
        """报告会话保存后的正式诊断结果；未保存即不可读"""
        if self._analysis is None:
            raise RuntimeError("诊断报告尚未保存")
        return self._analysis

    def _resolve_case(self, author: str, caseid: str) -> tuple[Any, str]:
        """案例写入必须属于本会话已领取且尚未提交的案例"""
        if caseid not in self.case_pool.cases:
            raise ValueError(f"caseid={caseid!r} 不属于当前 run 的案例池；请取 search_cases 返回的真实 ID")
        with self.case_pool.lock:
            runtime = dict(self.case_pool.case_runtime.get(caseid) or {})
        if runtime.get("owner") is None:
            raise ValueError("该案例尚未 claim：先 claim_case(case_id=...) 接手，再调用写入完成它")
        owner = runtime.get("owner")
        if owner is not None and owner != author:
            raise ValueError("该案例已由其他执行领取；请改取其他可领案例")
        if runtime.get("submitted"):
            raise ValueError("该案例已经 submit，禁止继续写入")
        invocation = author
        return self._case_writer(invocation), invocation

    def _case_writer(self, invocation: str) -> Any:
        """案例处置账本：按生产者惰性建立（标注语义写入原形，阶段=诊断）

        返回当前生产者的账本；case_writers 里存 (账本, 执行身份) 供报告保存折入。
        """
        existing = self.case_writers.get(invocation)
        if existing is not None:
            return existing[0]
        from src.agents.annotation.ledger import AnnotationToolLedger

        chapter = 0
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
        self.case_writers[invocation] = (ledger, invocation)
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

    def _unresolved_totals(self) -> dict[str, int]:
        """会话起始只见可领案例计数"""
        totals: dict[str, int] = {}
        for case in self.case_pool.search():
            if not case["submitted"] and not case["claimed"]:
                totals[str(case["case_type"])] = totals.get(str(case["case_type"]), 0) + 1
        return totals

    def _session_messages(self, role: str, material: dict[str, Any]) -> list[Any]:
        return [
            SystemMessage(content=build_diagnosis_system_prompt(self.novel_title, role)),
            HumanMessage(content=json.dumps({"role": role, "materials": material}, ensure_ascii=False)),
        ]

    def build_session_context(self, role: str, agent_id: str, observer: Any) -> DiagnosisWorkContext:
        with self.draft.publication_lock, self.lock:
            return self._build_session_context_locked(role, agent_id, observer)

    def _build_session_context_locked(self, role: str, invocation: str, observer: Any) -> DiagnosisWorkContext:
        from src.config import settings

        ledger = DiagnosisEvidenceLedger()
        self.ledgers[invocation] = ledger
        if invocation not in self.read_sessions:
            self.read_sessions[invocation] = self.session
        case_binding: CaseWriteBinding | None = None
        report: dict[str, Any] = {}
        if role == "report":
            self._require_cases_saved()
            self.reports[self.report_anchor] = report
            # 报告会话的叙事与报告写入以报告锚点为来源，随会话固定
            self.draft.producer_agent_id = invocation
            event_ids = list(self.draft.events)
            rows = [
                row
                for start in range(0, len(event_ids), 100)
                for row in self.draft.read_events(event_ids[start : start + 100])
            ]
            material: dict[str, Any] = {
                "catalog": [
                    {
                        "event_id": row["event_id"],
                        "title": row["title"],
                        "problem": row["problem"],
                        "status": row["status"],
                        "is_top_level": row["is_top_level"],
                        "top_level_event_id": row["top_level_event_id"],
                        "evidence": [
                            {
                                "paragraph_id": item["paragraph_id"],
                                "quote": item.get("quote"),
                                "occurrence": item.get("occurrence", 1),
                            }
                            for item in row.get("evidence", [])
                        ],
                    }
                    for row in rows
                ],
                "arcs": [{"arc_id": item.arc_id, "title": item.title} for item in self.draft.arcs.values()],
                "outcomes": [
                    {"outcome_id": item.outcome_id, "title": item.title} for item in self.draft.outcomes.values()
                ],
            }
        else:
            self.case_sessions.add(invocation)
            case_binding = CaseWriteBinding(
                resolve=lambda caseid: self._resolve_case(invocation, caseid), draft=self.draft
            )
            material = {"unresolved_case_totals": self._unresolved_totals()}
        graph_source = DiagnosisGraphSource(self.session, self.run_id)
        self.graph_sources.append(graph_source)
        tools = build_diagnosis_tools(
            self.read_sessions[invocation],
            self.run_id,
            role=role,
            evidence_ledger=ledger,
            organization_draft=self.draft,
            report_draft=report,
            case_pool=self.case_pool,
            agent_id=invocation,
            case_binding=case_binding,
            case_writes_graph=self._case_graph() if case_binding is not None else None,
            graph_source=graph_source,
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
            if original_function is not None and tool.name in {
                "claim_random_case", "claim_case", "submit_case", "push_case", "search_cases",
            }:

                def case_tool(*args: Any, _function: Any = original_function, _name: str = tool.name,
                              **kwargs: Any) -> Any:
                    waiting = time.perf_counter_ns()
                    with self.case_pool.lock:
                        started = time.perf_counter_ns()
                        try:
                            return _function(*args, **kwargs)
                        finally:
                            program.record_timing(_name, "lock_wait", started - waiting)
                            program.record_timing(_name, "execution", time.perf_counter_ns() - started)

                tool.func = case_tool
            elif original_function is not None and tool.name.startswith("write_"):

                def locked_tool(*args: Any, _function: Any = original_function, _name: str = tool.name,
                                **kwargs: Any) -> Any:
                    waiting = time.perf_counter_ns()
                    with self.draft.publication_lock, self.lock:
                        started = time.perf_counter_ns()
                        try:
                            return _function(*args, **kwargs)
                        finally:
                            program.record_timing(_name, "lock_wait", started - waiting)
                            program.record_timing(_name, "execution", time.perf_counter_ns() - started)

                tool.func = locked_tool
        program = DiagnosisProgramRuntime(
            tools,
            observer=observer,
            invocation_id=invocation,
            dialogue_total=lambda: len(self._case_dialogue_candidates()),
        )

        def complete() -> list[str]:
            if role != "report":
                unfinished = self.case_pool.unsubmitted_for(invocation)
                if unfinished:
                    return [f"仍有未提交案例 {unfinished}，请先办理并 submit_case"]
                return ["仍有可领案例，请用 claim_random_case() 领取并继续办理"] if self.case_counts()[0] else []
            try:
                self._require_cases_saved()
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

        max_rounds = settings.models.diagnosis.max_iterations
        messages = self._session_messages(role, material)
        return DiagnosisWorkContext(
            program, messages, lambda: self._complete_locked(complete), max_rounds,
            lambda: len(self.case_pool.claims_for(invocation)),
            lambda: len(self.case_pool.unsubmitted_for(invocation)),
        )

    def _complete_locked(self, check: Any) -> list[str]:
        with self.draft.publication_lock, self.lock:
            return check()

    def close(self) -> None:
        "释放领域持有的无连接读取入口"
        with self.lock:
            self.read_sessions.clear()
            self.graph_sources.clear()

    def abort_session(self, author: str) -> None:
        "释放失败会话的未保存领取、提交与事实贡献，保留案例登记"
        self.case_pool.abandon(author)
        with self.draft.publication_lock, self.lock:
            if author in self.session_saved:
                return
            self.case_sessions.discard(author)
            self.case_writers.pop(author, None)
            self.ledgers.pop(author, None)
            self.read_sessions.pop(author, None)
            if self._case_graph_value is not None:
                self._case_graph_value.rollback(author)
            for name in ("events", "containments", "relations", "arcs", "event_arc_links", "outcomes",
                         "event_outcome_links"):
                records = getattr(self.draft, name)
                for key in [key for key, item in records.items() if item.producer_agent_id == author]:
                    del records[key]
            self.draft.refresh_read_cache()

    def retain_pending_cases(self, error: BaseException) -> None:
        """失败或取消只短事务保留登记，不采用交付、不重写已保存产物

        会话完成的保存已经落库、不再回退；未保存会话只保留案例登记（不落提交与
        交付），其案例按未解决留给续跑的会话重办。
        """
        from src.case_pool.contributions import CaseContribution

        with self.draft.publication_lock, self.lock:
            with self.case_pool.lock:
                authors = sorted(self.case_pool.registrations)
            contributions = [
                CaseContribution(
                    self.run_id,
                    author,
                    json.dumps(
                        {**self.case_pool.contribution(author), "submissions": []},
                        ensure_ascii=False,
                    ),
                )
                for author in authors
                if author not in self.case_pool.saved and self.case_pool.registrations.get(author)
            ]
            try:
                if contributions:
                    self.session.diagnosis.retain_pending(self.run_id, self.agent_id, tuple(contributions))
            finally:
                for author in authors:
                    self.case_pool.abandon(author)

    def _narrative_snapshot(self) -> str:
        return snapshot_digest(
            {
                "identity": self.draft.content_digest(),
                "structure": self.draft.structure_digest(),
                **{
                    name: record_payloads(getattr(self.draft, name).values())
                    for name in ("arcs", "event_arc_links", "outcomes", "event_outcome_links")
                },
            }
        )


def create_diagnosis_domain(
    *, session: Storage, run_id: str, novel_id: str, agent_id: str, novel_title: str | None = None
) -> DiagnosisDomain:
    """诊断解析 diagnosis_model_id 对应的池条目；未指定时每个会话由模型池选举，
    model_id 仅作计数标识，不读取窗口或容量数字。"""
    from src.config import settings

    model_id = settings.models.diagnosis_model_id
    entry = next((item for item in settings.models.model_pool if item.model_id == model_id), None)
    if model_id is not None and entry is None:
        raise ValueError("诊断模型不在模型池中")
    return DiagnosisDomain(
        session=session,
        run_id=run_id,
        novel_id=novel_id,
        agent_id=agent_id,
        novel_title=novel_title,
        model_id=entry.model_id if entry is not None else "",
    )
