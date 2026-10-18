"诊断正式组织的物理保存；领域验证由发布前的正式业务链完成"

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session as Storage

from src.storage.ids import new_id
from src.storage.models import ConflictClaim as ConflictClaimRow
from src.storage.models import ConflictRecord, Execution, NarrativeGroup, NarrativeLink
from src.storage.models.base import naive_utcnow
from src.storage.repositories.narrative_records import write_evidence_rows as _write_evidence_rows
from src.storage.repositories.queries import event_trees_organization as _org_queries


def register_diagnosis_session(session: Storage, *, run_id: str, session_id: str) -> None:
    "登记诊断整轮身份（executions 的 session 形状）；已存在且同 run 时幂等，不覆盖既有轮次"
    existing = _org_queries.event_trees_organization_register_diagnosis_session_1(session, session_id)
    if existing is None:
        session.add(Execution(execution_id=session_id, session_run_id=run_id, session_created_at=naive_utcnow()))
        session.flush()
        return
    if existing.session_run_id != run_id:
        raise ValueError("诊断会话身份已属于其他运行")


def register_diagnosis_execution(
    session: Storage, *, run_id: str, execution_id: str, role: str, attempt_number: int, case_anchor: str | None = None
) -> None:
    "登记诊断案例/报告的真实尝试；执行事实与诊断上下文同事务写入"
    existing = _org_queries.event_trees_organization_register_diagnosis_execution_1(session, execution_id)
    if existing is not None:
        if (
            existing.run_id != run_id
            or existing.role != role
            or existing.case_anchor != case_anchor
            or (existing.attempt_number != attempt_number)
        ):
            raise ValueError("诊断执行身份已登记为其他归属或尝试序号")
        return
    duplicate = _org_queries.event_trees_organization_register_diagnosis_execution_2(
        session, attempt_number, case_anchor, role, run_id
    )
    if duplicate is not None:
        raise ValueError("诊断执行的该次尝试已有真实执行")
    session.add(
        Execution(
            execution_id=execution_id,
            run_id=run_id,
            role=role,
            case_anchor=case_anchor,
            attempt_number=attempt_number,
            started_at=naive_utcnow(),
            status="running",
        )
    )
    session.flush()


def _require_report(session: Storage, run_id: str, report_id: str, session_id: str | None) -> Any:
    "正式组织必须与本次诊断会话的报告一同保存，不接受其他产物冒充"
    report = _org_queries.event_trees_organization_require_report_1(session, report_id)
    if report is None:
        raise ValueError("全书组织必须与本任务诊断报告一同保存")
    owner = _org_queries.event_trees_organization_require_report_2(session, report)
    if owner is None or owner.session_run_id != run_id:
        raise ValueError("诊断报告不属于本运行")
    if session_id is not None and report.session_id != session_id:
        raise ValueError("诊断报告与本次诊断会话不一致")
    return report


def save_organization(session: Storage, run_id: str, organization: Any, report_id: str) -> None:
    "与诊断报告共用调用方事务；只替换本 run 的诊断组织，不改章节事件"
    _require_report(session, run_id, report_id, organization.source_execution_id)
    if list(_org_queries.event_trees_organization_published_arc_ids_1(session, run_id)):
        raise ValueError("叙事组织已发布，禁止替换旧运行产物")
    pending = {arc.arc_id: arc for arc in organization.arcs}
    saved: set[str] = set()
    while pending:
        ready = [arc for arc in pending.values() if arc.parent_arc_id is None or arc.parent_arc_id in saved]
        if not ready:
            raise ValueError("叙事线父级不存在或形成环，不能发布")
        for arc in ready:
            session.add(
                NarrativeGroup(
                    group_id=arc.arc_id,
                    producer_execution_id=arc.producer_invocation_id,
                    title=arc.title,
                    arc_kind=arc.kind,
                    arc_objective=arc.objective,
                    arc_role=arc.role,
                    arc_reason=arc.reason,
                    parent_arc_id=arc.parent_arc_id,
                )
            )
            saved.add(arc.arc_id)
            del pending[arc.arc_id]
        session.flush()
    for arc in organization.arcs:
        _write_evidence_rows(session, {"narrative_group_id": arc.arc_id}, arc.evidence)
    for item in organization.outcomes:
        session.add(
            NarrativeGroup(
                group_id=item.outcome_id,
                producer_execution_id=item.producer_invocation_id,
                title=item.title,
                outcome_description=item.description,
            )
        )
    session.flush()
    for item in organization.outcomes:
        _write_evidence_rows(session, {"narrative_group_id": item.outcome_id}, item.evidence)
    for link in organization.event_arc_links:
        link_id = new_id()
        session.add(
            NarrativeLink(
                link_id=link_id,
                producer_execution_id=link.producer_invocation_id,
                reason=link.reason,
                member_event_id=link.event_id,
                arc_group_id=link.arc_id,
                arc_role=link.role,
            )
        )
        _write_evidence_rows(session, {"narrative_link_id": link_id}, link.evidence)
    for outcome_link in organization.event_outcome_links:
        link_id = new_id()
        session.add(
            NarrativeLink(
                link_id=link_id,
                producer_execution_id=outcome_link.producer_invocation_id,
                reason=outcome_link.reason,
                member_event_id=outcome_link.event_id,
                outcome_group_id=outcome_link.outcome_id,
            )
        )
        _write_evidence_rows(session, {"narrative_link_id": link_id}, outcome_link.evidence)
    session.flush()
    _write_conflicts(session, organization)
    session.flush()


def _write_conflicts(session: Storage, organization: Any) -> None:
    "冲突登记：主体恰一类型，每条陈述保留自己的来源与独立证据"
    subject_columns = {"event": "subject_event_id", "declaration": "subject_declaration_id", "fact": "subject_fact_id"}
    for conflict in organization.conflicts:
        subject_id: Any = str(conflict.subject_id)
        session.add(
            ConflictRecord(
                conflict_id=conflict.conflict_id,
                producer_execution_id=conflict.producer_invocation_id,
                reason=conflict.reason,
                **{subject_columns[conflict.subject_kind]: subject_id},
            )
        )
        session.flush()
        for ordinal, claim in enumerate(conflict.claims):
            claim_id = new_id()
            session.add(
                ConflictClaimRow(
                    claim_id=claim_id,
                    conflict_id=conflict.conflict_id,
                    claim_ordinal=ordinal,
                    producer_execution_id=claim.producer_invocation_id,
                    claim_text=claim.claim,
                )
            )
            session.flush()
            _write_evidence_rows(session, {"claim_id": claim_id}, claim.evidence)
        _write_evidence_rows(session, {"conflict_id": conflict.conflict_id}, conflict.evidence)
    session.flush()
