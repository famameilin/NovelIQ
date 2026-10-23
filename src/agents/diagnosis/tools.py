"诊断 Agent 的案例、业务写入和读取工具"

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Annotated, Any

from langchain_core.tools import tool
from pydantic import Field

from src.agents.annotation.links import build_text_read_tool
from src.agents.annotation.shared_tools import build_case_tools, build_finish_tool, build_state_read_tools
from src.agents.annotation.text_search import TextSearchService
from src.agents.annotation.tools import _forbid_undeclared_args, build_search_tools
from src.diagnosis.patch import AgentAnalysisPatch
from src.diagnosis.schema import AgentAnalysis
from src.event_trees.organization import EventOrganizationDraft
from src.storage import Storage

from .evidence import DiagnosisEvidenceLedger
from .inputs import ArcWriteItem, EventWriteItem, OutcomeWriteItem, WriteItem
from .read_context import (
    DiagnosisAnnotationEventSource,
    DiagnosisGraphSource,
    DiagnosisOrganizationSource,
    DiagnosisTextAccess,
    DiagnosisTextQuery,
    graph_signals,
)
from .roster import character_names, normalize_character_name

WRITE_NAMES = frozenset(
    {"write_diagnosis", "write_event", "write_arc", "write_outcome", "write_entity", "write_relation", "write_dialogue"}
)

#: 案例写入先核验领取，读取与报告收尾不关联案例
CASE_WRITE_NAMES = frozenset(
    {"write_event", "write_arc", "write_outcome", "write_entity", "write_relation", "write_dialogue"}
)


def _write_items(items: Sequence[WriteItem], handlers: dict[str, Any]) -> str:
    """逐项调用原领域原语，业务拒绝仅影响该项；系统故障直接抛出"""
    results: list[Any] = []
    failed: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        operation = item.model_dump()["operation"]
        args = {key: getattr(item, key) for key in type(item).model_fields if key != "operation"}
        try:
            results.append(handlers[operation](**args))
        except ValueError as exc:
            results.append(None)
            failed.append({"index": index, "operation": operation, "message": str(exc)})
    return json.dumps(
        {"status": "partial" if failed else "written", "results": results, "failed": failed}, ensure_ascii=False
    )


def _case_write_tools(query: Any, binding: Any, graph: Any) -> list[Any]:
    """人物/关系/对话案例处置复用标注语义写入原形，核验 caseid 领取后使用当前生产者账本与图作者"""
    from src.agents.diagnosis.case_write_tools import build_case_write_tools

    built = build_case_write_tools(query, binding)

    def _guard(candidate: Any) -> Any:
        original_func, original_coroutine = candidate.func, candidate.coroutine

        def invoke(*args: Any, **kwargs: Any) -> Any:
            _writer, author = binding.writer()
            with graph.author(author):
                snapshot = graph.snapshot()
                try:
                    return original_func(*args, **kwargs)
                except BaseException:
                    graph.restore(snapshot)
                    raise

        async def ainvoke(*args: Any, **kwargs: Any) -> Any:
            _writer, author = binding.writer()
            with graph.author(author):
                snapshot = graph.snapshot()
                try:
                    return await original_coroutine(*args, **kwargs)
                except BaseException:
                    graph.restore(snapshot)
                    raise

        if original_func is not None:
            candidate.func = invoke
        if original_coroutine is not None:
            candidate.coroutine = ainvoke
        return candidate

    return [_guard(candidate) for candidate in built]


def build_diagnosis_tools(
    session: Storage,
    run_id: str,
    *,
    role: str = "case",
    evidence_ledger: DiagnosisEvidenceLedger | None = None,
    organization_draft: EventOrganizationDraft | None = None,
    report_draft: dict[str, Any] | None = None,
    case_pool: Any = None,
    agent_id: str = "",
    text_search: TextSearchService | None = None,
    case_binding: Any = None,
    case_writes_graph: Any | None = None,
    case_view: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    graph_source: DiagnosisGraphSource | None = None,
    character_roster: Sequence[str] | None = None,
) -> list[Any]:
    """装配真实诊断身份：角色裁剪写入面，案例写入保留显式 caseid 关联"""
    from src.case_pool import CasePool

    ledger = evidence_ledger or DiagnosisEvidenceLedger()
    draft = organization_draft or EventOrganizationDraft(session, run_id, agent_id)
    report = report_draft if report_draft is not None else {}
    if case_pool is None:
        case_pool = CasePool(run_id)
        case_pool.load_storage(session)
    author = agent_id
    case_pool.begin(author)

    roster = (
        None
        if character_roster is None
        else {normalize_character_name(name): name for name in character_roster}
    )

    def validate_character_references(analysis: AgentAnalysis) -> None:
        """弧线评分与人物名单只接受本 run 的正式角色规范名"""
        nonlocal roster
        references = {
            "arc_scores": list(analysis.arc_scores),
            "focus_characters": analysis.focus_characters,
            "main_characters": analysis.main_characters,
            "core_cast": analysis.core_cast,
        }
        if not any(references.values()):
            return
        if roster is None:
            roster = character_names(session, run_id)
        allowed = roster
        unknown = {
            field: [name for name in names if normalize_character_name(name) not in allowed]
            for field, names in references.items()
        }
        unknown = {field: names for field, names in unknown.items() if names}
        if not unknown:
            return
        known = sorted(allowed.values())
        listing = "、".join(known[:100])
        if not known:
            listing = "本 run 尚无正式角色"
        elif len(known) > 100:
            listing += f"…（共 {len(known)} 个，完整名单用 search_graph(entity_type=\"character\") 分页读取）"
        raise ValueError(
            f"以下名字不是本 run 的正式角色，arc_scores 与人物名单只接受角色规范名: {unknown}；"
            f"可用角色规范名: {listing}；核对后用 write_diagnosis(patch=...) 修正对应字段"
        )

    @tool
    def write_event(items: Annotated[list[EventWriteItem], Field(min_length=1, max_length=300)]) -> str:
        """批量提交事件核对、完整事件身份判断、跨章事件、显式包含/其他关系或事件核对"""
        return _write_items(
            items,
            {
                "event": draft.event,
                "contain": draft.contain,
                "relation": draft.relate_events,
                "review": draft.review_events,
                "retract": draft.retract,
                "structure_review": draft.structure_review,
            },
        )

    @tool
    def write_arc(items: Annotated[list[ArcWriteItem], Field(min_length=1, max_length=300)]) -> str:
        """批量写主支线或事件关联，operation=arc/link；各项分别给出理由及原文证据

        标题最多6字，目标最多20字，不计算标点；标题精练单一、目标一句，超限精简后重写
        """
        return _write_items(items, {"arc": draft.register_arc, "link": draft.link_event_arc})

    @tool
    def write_outcome(items: Annotated[list[OutcomeWriteItem], Field(min_length=1, max_length=300)]) -> str:
        """批量写全书结果或顶层事件贡献，operation=outcome/link；不自动替换子事件端点

        标题最多6字，说明最多20字，不计算标点；标题精练单一、说明一句，超限精简后重写
        """
        return _write_items(items, {"outcome": draft.register_outcome, "link": draft.link_event_outcome})

    @tool
    def write_diagnosis(analysis: AgentAnalysis | None = None, patch: AgentAnalysisPatch | None = None) -> str:
        """提交报告或明确修订，analysis 与 patch 恰选一项，失败不覆盖有效草稿"""
        if (analysis is None) == (patch is None):
            raise ValueError("write_diagnosis 必须且只能提供 analysis 或 patch")
        if patch is not None:
            if "analysis" not in report:
                raise ValueError("尚无报告草稿，请先 write_diagnosis(analysis=...)")
            analysis = AgentAnalysis.model_validate(
                {**report["analysis"], **patch.model_dump(exclude_unset=True, mode="json")}
            )
        if analysis is None:
            raise ValueError("诊断报告不能为空")
        validate_character_references(analysis)
        report["analysis"] = analysis.model_dump(mode="json")
        return json.dumps({"status": "written", "record": "diagnosis_report"}, ensure_ascii=False)

    @tool
    def read_metrics() -> str:
        """读真实聚合指标与转折、高张力、伏笔、关系变化、图谱统计素材；不重算指标或吞系统故障

        伏笔条目的 event_id 是来源事件，事件关联只能用同一项的 event_id；event_id 为空表示尚无正式事件身份
        """
        from src.diagnosis.queries import DiagnosisQueries

        repo = DiagnosisQueries(session)
        ledger.record_tool_call("read_metrics")
        payload = {
            "aggregate": session.statistics.fetch_global_stats_dict(run_id),
            "pivots": [
                {"chapter_id": chapter_id, "text": text[:300], "event_type": event_type}
                for chapter_id, text, event_type in repo.fetch_pivot_blocks(run_id, limit=20)
            ],
            "high_tension": [
                {"paragraph_id": paragraph_id, "text": text[:300], "tension": tension}
                for paragraph_id, text, tension in repo.fetch_high_tension_chunks(run_id, limit=10)
            ],
            "foreshadowing": repo.fetch_foreshadowing_sources(run_id),
            "foreshadow_expectation": repo.calculate_foreshadow_expectation(run_id),
            "relation_changes": [
                {
                    "chapter_id": chapter_id,
                    "from_name": left,
                    "to_name": right,
                    "relation_type": kind,
                    "change_kind": change,
                }
                for chapter_id, left, right, kind, change in repo.fetch_relation_changes(run_id, limit=50)
            ],
            "graph_signals": graph_signals(session, run_id),
        }
        return json.dumps(payload, ensure_ascii=False)

    @tool
    def read_topics() -> str:
        """读取真实 topic_id、累计权重、主题词及标签；报告逐一覆盖这些 ID，不按排序猜测"""
        from src.diagnosis.queries import DiagnosisQueries

        ledger.record_tool_call("read_topics")
        return json.dumps({"topics": DiagnosisQueries(session).fetch_topic_words(run_id)}, ensure_ascii=False)

    access = DiagnosisTextAccess(run_id)
    query = DiagnosisTextQuery(session, run_id, text_search)
    state_tools = build_state_read_tools(
        graph_source if graph_source is not None else DiagnosisGraphSource(session, run_id),
        DiagnosisAnnotationEventSource(draft),
        event_reads={},
        entity_ids=set(),
        case_reads=[],
        resolve_event=lambda value: value,
        organization=DiagnosisOrganizationSource(draft),
    )
    read_text = build_text_read_tool(query, access)
    common: list[Any] = [
        *build_search_tools(query, access),
        read_text,
        *state_tools,
        *[
            candidate for candidate in build_case_tools(case_pool, author, case_view=case_view)
            if role != "report" or candidate.name == "search_cases"
        ],
        build_finish_tool(lambda: {"status": "end_requested"}),
    ]
    if role == "report":
        tools: list[Any] = [write_arc, write_outcome, write_diagnosis, read_metrics, read_topics, *common]
    else:
        tools = [write_event, *common]
        if case_binding is not None and case_writes_graph is not None:
            # 三类案例处置复用标注语义写入原形；caseid 核验领取，来源与账本归属当前生产者
            tools.extend(_case_write_tools(query, case_binding, case_writes_graph))

    from src.case_pool.tool_binding import bind_caseid

    for candidate in tools:
        _forbid_undeclared_args(candidate)
        prepare = case_binding.select if case_binding is not None and candidate.name in CASE_WRITE_NAMES else None
        if candidate.name not in {"claim_case", "claim_random_case", "submit_case"}:
            bind_caseid(candidate, prepare=prepare)
    return tools
