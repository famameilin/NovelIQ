"""诊断五个写入面与两个指标读取面，其余工具使用标注的同一实现"""

from __future__ import annotations

import json
from collections.abc import Sequence
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
from .inputs import ArcWriteItem, ConflictItem, EventWriteItem, OutcomeWriteItem, WriteItem
from .read_context import (
    DiagnosisDeclarationSource,
    DiagnosisGraphSource,
    DiagnosisOrganizationSource,
    DiagnosisTextAccess,
    DiagnosisTextQuery,
    graph_signals,
)

WRITE_NAMES = frozenset(
    {
        "write_diagnosis",
        "write_event",
        "write_arc",
        "write_outcome",
        "write_conflict",
        "write_entity",
        "write_relation",
        "write_dialogue",
    }
)


def _write_items(items: Sequence[WriteItem], handlers: dict[str, Any]) -> str:
    """逐项调用原领域原语，业务拒绝仅影响该项；系统故障直接抛出"""
    results: list[Any] = []
    failed: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        operation = getattr(item, "operation", "conflict")
        args = {key: getattr(item, key) for key in type(item).model_fields if key != "operation"}
        try:
            results.append(handlers[operation](**args))
        except ValueError as exc:
            results.append(None)
            failed.append({"index": index, "operation": operation, "message": str(exc)})
    return json.dumps(
        {"status": "partial" if failed else "written", "results": results, "failed": failed}, ensure_ascii=False
    )


def build_diagnosis_tools(
    session: Storage,
    run_id: str,
    *,
    evidence_ledger: DiagnosisEvidenceLedger | None = None,
    organization_draft: EventOrganizationDraft | None = None,
    report_draft: dict[str, Any] | None = None,
    case_pool: Any = None,
    execution_id: str = "",
    text_search: TextSearchService | None = None,
    case_id: str | None = None,
    producer_invocation_id: str | None = None,
    case_writes_graph: Any | None = None,
    case_source_chapter: int | None = None,
    case_dialogue_candidates: list[Any] | None = None,
    case_writer_store: dict[str, Any] | None = None,
) -> list[Any]:
    """装配真实诊断身份，保留正式原文绑定、案例关联和结束检查职责"""
    from src.case_pool import CasePool

    ledger = evidence_ledger or DiagnosisEvidenceLedger()
    draft = organization_draft or EventOrganizationDraft(session, run_id, execution_id)
    report = report_draft if report_draft is not None else {}
    if case_pool is None:
        case_pool = CasePool(run_id)
        case_pool.load_storage(session)
    author = producer_invocation_id or execution_id
    case_pool.begin(author)

    @tool
    def write_event(items: Annotated[list[EventWriteItem], Field(min_length=1, max_length=300)]) -> str:
        """批量提交声明核对、身份阶段判断、跨章事件、显式包含/其他关系或事件核对"""
        return _write_items(
            items,
            {
                "identity": draft.identity,
                "event": draft.event,
                "contain": draft.contain,
                "declaration_review": draft.review_declarations,
                "relation": draft.relate_events,
                "review": draft.review_events,
                "compare": draft.compare_declarations,
                "retract": draft.retract,
                "structure_review": draft.structure_review,
            },
        )

    @tool
    def write_arc(items: Annotated[list[ArcWriteItem], Field(min_length=1, max_length=300)]) -> str:
        """批量写主支线或事件关联，operation=arc/link；各项分别给出理由及原文证据"""
        return _write_items(items, {"arc": draft.register_arc, "link": draft.link_event_arc})

    @tool
    def write_outcome(items: Annotated[list[OutcomeWriteItem], Field(min_length=1, max_length=300)]) -> str:
        """批量写全书结果或顶层事件贡献，operation=outcome/link；不自动替换子事件端点"""
        return _write_items(items, {"outcome": draft.register_outcome, "link": draft.link_event_outcome})

    @tool
    def write_conflict(items: Annotated[list[ConflictItem], Field(min_length=1, max_length=300)]) -> str:
        """批量保留冲突对象、各说法及各自证据；原冲突校验保持，不裁定唯一答案"""
        return _write_items(items, {"conflict": draft.register_conflict})

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
        report["analysis"] = analysis.model_dump(mode="json")
        return json.dumps({"status": "written", "record": "diagnosis_report"}, ensure_ascii=False)

    @tool
    def read_metrics() -> str:
        """读真实聚合指标与转折、高张力、伏笔、关系变化、图谱统计素材；不重算指标或吞系统故障"""
        from src.diagnosis.queries import DiagnosisQueries

        pass

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
        DiagnosisGraphSource(session, run_id),
        DiagnosisDeclarationSource(draft),
        event_reads={},
        entity_ids=set(),
        case_reads=[],
        resolve_event=lambda value: value,
        organization=DiagnosisOrganizationSource(draft),
    )
    read_text = build_text_read_tool(query, access)
    tools = [
        write_diagnosis,
        write_event,
        write_arc,
        write_outcome,
        write_conflict,
        read_metrics,
        read_topics,
        *build_search_tools(query, access),
        read_text,
        *state_tools,
        *build_case_tools(case_pool, author),
        build_finish_tool(lambda: {"status": "end_requested"}),
    ]
    if case_writes_graph is not None and case_writer_store is not None and case_id is not None:
        # 2026-10-15 用户裁定「复用标注工具」「没权限」：人物/关系/对话案例处置复用
        # 标注语义写入工具原形；来源章归属本案例责任声明所在章，对话候选来自持久化对话记录
        from src.agents.annotation.ledger import AnnotationToolLedger
        from src.agents.diagnosis.case_write_tools import build_case_write_tools

        writer = AnnotationToolLedger(
            run_scope=run_id,
            current_chapter_id=int(case_source_chapter or 0),
            current_chapter_text="",
            allow_future_context=False,
        )
        writer.phase = "diagnosis_open"
        writer.graph = case_writes_graph
        writer.dialogue.dialogue_candidates = list(case_dialogue_candidates or [])
        case_author = author
        case_writes_graph.begin(case_author, int(case_source_chapter or 0), "case")
        case_tools = build_case_write_tools(query, writer)
        case_writer_store[case_id] = (writer, case_author)

        def _bind_case_execution(candidate: Any) -> Any:
            original_func, original_coroutine = candidate.func, candidate.coroutine

            def invoke(*args: Any, **kwargs: Any) -> Any:
                with case_writes_graph.author(case_author):
                    snapshot = case_writes_graph.snapshot()
                    try:
                        return original_func(*args, **kwargs)
                    except BaseException:
                        case_writes_graph.restore(snapshot)
                        raise

            async def ainvoke(*args: Any, **kwargs: Any) -> Any:
                with case_writes_graph.author(case_author):
                    snapshot = case_writes_graph.snapshot()
                    try:
                        return await original_coroutine(*args, **kwargs)
                    except BaseException:
                        case_writes_graph.restore(snapshot)
                        raise

            if original_func is not None:
                candidate.func = invoke
            if original_coroutine is not None:
                candidate.coroutine = ainvoke
            return candidate

        tools.extend(_bind_case_execution(candidate) for candidate in case_tools)

    from src.case_pool.tool_binding import bind_caseid, current_case_call_id

    def associate(*, caseid: Any, tool_name: str, receipt: dict[str, Any]) -> dict[str, Any]:
        return case_pool.associate(
            caseid,
            author,
            tool_name=tool_name,
            call_id=current_case_call_id.get(),
            receipt=receipt,
            is_write=tool_name in WRITE_NAMES,
        )

    for candidate in tools:
        _forbid_undeclared_args(candidate)
        bind_caseid(candidate, associate)
    return tools
