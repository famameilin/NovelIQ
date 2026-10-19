"报告、事件组织、案例采纳与归因整体提交"

import json
from types import SimpleNamespace

from sqlalchemy import select, text

from src.storage.models import Agent, AnalysisAssessment, DiagnosisReport
from src.storage.repositories import narrative_records
from src.storage.repositories.case_writes import CaseWritesRepository
from src.storage.repositories.diagnosis_event_writes import save_diagnosis_events
from src.storage.repositories.fact_writes import FactWriter
from src.storage.repositories.organization_writes import save_organization


def _record(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{key: _record(item) for key, item in value.items()})
    if isinstance(value, list):
        return [_record(item) for item in value]
    return value


def save_report(session, request):
    "正式报告、叙事组织与案例采纳在同一事务保存"
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"fact_graph:{request.run_id}"}
    )
    owner = session.get(Agent, request.agent_id)
    if owner is None or owner.run_id != request.run_id:
        raise ValueError("诊断报告缺少本运行的真实会话")
    existing = session.scalar(
        select(DiagnosisReport).join(Agent, Agent.id == DiagnosisReport.agent_id).where(Agent.run_id == request.run_id)
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
        for key in ("current_attribution_agent_id", "speaker_entity_id", "tone", "is_inner_monologue"):
            setattr(row, key, change[key])
    warnings = []
    warnings_by_author = {}
    for frozen in request.cases:
        saved_warnings = CaseWritesRepository(request.run_id).save_work(session, frozen, adopted_output_id=report_id)
        warnings_by_author[frozen.author] = saved_warnings
        warnings.extend(saved_warnings)
    session.flush()
    return {"report_id": report_id, "warnings": warnings, "warnings_by_author": warnings_by_author}


def retain_pending(session, run_id, agent_id, contributions):
    # 已发布但内存确认失败时，不能把采用交付改写为空登记
    if session.scalar(select(DiagnosisReport.report_id).where(DiagnosisReport.agent_id == agent_id)) is not None:
        return
    for frozen in contributions:
        warnings = CaseWritesRepository(run_id).save_work(session, frozen)
        if warnings:
            raise RuntimeError(f"诊断失败案例未完整保存: {warnings}")


def session_rows(session, run_id):
    from src.storage.models import DIAGNOSIS_ROLES, NarrativeLink, OrganizationCheck

    executions = list(session.scalars(select(Agent).where(Agent.run_id == run_id, Agent.type.in_(DIAGNOSIS_ROLES))))
    identifiers = [row.id for row in executions]
    return {
        "agent": executions,
        "links": list(session.scalars(select(NarrativeLink).where(NarrativeLink.producer_agent_id.in_(identifiers)))),
        "checks": list(
            session.scalars(select(OrganizationCheck).where(OrganizationCheck.producer_agent_id.in_(identifiers)))
        ),
    }


def save_session(session, request):
    from src.storage.repositories.diagnosis_event_writes import save_case_session_rows

    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"fact_graph:{request.run_id}"}
    )
    owner = session.get(Agent, request.agent_id)
    if owner is None or owner.run_id != request.run_id or owner.type != "case":
        raise ValueError("案例会话缺少本运行的真实执行")
    if narrative_records.run_declaration_ids(session, request.run_id) != set(request.declaration_ids):
        raise ValueError("案例会话保存期间原始声明清单发生变化")
    draft = SimpleNamespace(
        **{
            name: {key: _record(value) for key, value in items.items()}
            for name, items in json.loads(request.organization_json).items()
        }
    )
    save_case_session_rows(session, request.run_id, request.agent_id, draft)
    for frozen in request.facts:
        FactWriter(request.run_id).save_work(session, frozen, "")
    for change in request.dialogue_updates:
        row = narrative_records.dialogue_record_by_candidate(session, request.run_id, change["candidate_key"])
        if row is None:
            raise ValueError(f"对话候选缺少持久化记录: {change['candidate_key']}")
        for key in ("current_attribution_agent_id", "speaker_entity_id", "tone", "is_inner_monologue"):
            setattr(row, key, change[key])
    for frozen in request.cases:
        warnings = CaseWritesRepository(request.run_id).save_work(session, frozen)
        if warnings:
            raise ValueError(f"案例会话交付未完整保存: {warnings}")
    session.flush()
