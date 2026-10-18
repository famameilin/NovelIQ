"报告、事件组织、案例采纳与归因整体提交"

import json
from types import SimpleNamespace

from sqlalchemy import func, select, text

from src.storage.models import AnalysisAssessment, CaseEntry, DiagnosisReport, Execution
from src.storage.repositories import narrative_records
from src.storage.repositories.case_writes import CaseWritesRepository
from src.storage.repositories.diagnosis_event_writes import save_diagnosis_events
from src.storage.repositories.fact_writes import FactWriter
from src.storage.repositories.organization_writes import (
    save_organization,
)


def _record(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{key: _record(item) for key, item in value.items()})
    if isinstance(value, list):
        return [_record(item) for item in value]
    return value


def publish(session, request):
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"fact_graph:{request.run_id}"}
    )
    owner = session.get(Execution, request.session_id)
    if owner is None or owner.session_run_id != request.run_id:
        raise ValueError("诊断报告缺少本运行的真实会话")
    existing = session.scalar(
        select(DiagnosisReport)
        .join(Execution, Execution.execution_id == DiagnosisReport.session_id)
        .where(Execution.session_run_id == request.run_id)
    )
    if existing is not None:
        raise ValueError("本运行已有正式报告；请先核验原冻结发布结果")
    if narrative_records.run_declaration_ids(session, request.run_id) != set(request.declaration_ids):
        raise ValueError("诊断发布期间原始声明清单发生变化")
    report_id = request.report["report_id"]
    session.add(DiagnosisReport(**request.report))
    session.flush()
    session.add_all(AnalysisAssessment(**row) for row in request.assessments)
    session.flush()
    organization = _record(json.loads(request.organization_json))
    save_diagnosis_events(session, request.run_id, organization, report_id)
    save_organization(session, request.run_id, organization, report_id)
    for frozen in request.facts:
        FactWriter(request.run_id).save_work(session, frozen, report_id)
    for change in request.dialogue_updates:
        row = narrative_records.dialogue_record_by_candidate(session, request.run_id, change["candidate_key"])
        if row is None:
            raise ValueError(f"对话候选缺少持久化记录: {change['candidate_key']}")
        for key in ("current_attribution_execution_id", "speaker_entity_id", "tone", "is_inner_monologue"):
            setattr(row, key, change[key])
    warnings = []
    warnings_by_author = {}
    for frozen in request.cases:
        saved_warnings = CaseWritesRepository(request.run_id).save_work(session, frozen, adopted_output_id=report_id)
        warnings_by_author[frozen.author] = saved_warnings
        warnings.extend(saved_warnings)
    session.flush()
    return {"report_id": report_id, "warnings": warnings, "warnings_by_author": warnings_by_author}


def retain_pending(session, run_id, session_id, contributions):
    # 已发布但内存确认失败时，不能把采用交付改写为空登记
    if session.scalar(select(DiagnosisReport.report_id).where(DiagnosisReport.session_id == session_id)) is not None:
        return
    for frozen in contributions:
        warnings = CaseWritesRepository(run_id).save_work(session, frozen)
        if warnings:
            raise RuntimeError(f"诊断失败案例未完整保存: {warnings}")


def saved_case_warnings(session, run_id, report_id):
    "按真实执行恢复已发布报告的案例告警，不跨运行读取回执"
    report = session.scalar(
        select(DiagnosisReport.report_id)
        .join(Execution, Execution.execution_id == DiagnosisReport.session_id)
        .where(DiagnosisReport.report_id == report_id, Execution.session_run_id == run_id)
    )
    if report is None:
        raise ValueError("正式诊断报告不属于当前运行")
    result = {}
    rows = session.scalars(
        select(CaseEntry)
        .where(CaseEntry.warning_report_id == report_id)
        .order_by(CaseEntry.producer_execution_id, CaseEntry.warning_ordinal)
    )
    for row in rows:
        result.setdefault(str(row.producer_execution_id), []).append(
            {"code": "case_save_failed", "caseid": row.attempted_case_reference, "message": row.warning_message}
        )
    return result


def next_attempt(session, run_id, role, case_anchor):
    return (
        int(
            session.scalar(
                select(func.count())
                .select_from(Execution)
                .where(Execution.run_id == run_id, Execution.role == role, Execution.case_anchor == case_anchor)
            )
            or 0
        )
        + 1
    )
