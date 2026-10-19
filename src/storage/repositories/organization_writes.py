"诊断正式组织的物理保存；领域验证由发布前的正式业务链完成"

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session as Storage

from src.storage.ids import new_id
from src.storage.models import NarrativeGroup, NarrativeLink
from src.storage.repositories.narrative_records import write_evidence_rows as _write_evidence_rows
from src.storage.repositories.queries import event_trees_organization as _org_queries


def _require_report(session: Storage, run_id: str, report_id: str, agent_id: str | None) -> Any:
    "正式组织必须与本次诊断会话的报告一同保存，不接受其他产物冒充"
    report = _org_queries.event_trees_organization_require_report_1(session, report_id)
    if report is None:
        raise ValueError("全书组织必须与本任务诊断报告一同保存")
    owner = _org_queries.event_trees_organization_require_report_2(session, report)
    if owner is None or owner.run_id != run_id:
        raise ValueError("诊断报告不属于本运行")
    if agent_id is not None and report.agent_id != agent_id:
        raise ValueError("诊断报告与本次诊断会话不一致")
    return report


def save_organization(session: Storage, run_id: str, organization: Any, report_id: str) -> None:
    "与诊断报告共用调用方事务；只替换本 run 的诊断组织，不改章节事件"
    _require_report(session, run_id, report_id, organization.source_agent_id)
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
                    producer_agent_id=arc.producer_agent_id,
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
                producer_agent_id=item.producer_agent_id,
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
                producer_agent_id=link.producer_agent_id,
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
                producer_agent_id=outcome_link.producer_agent_id,
                reason=outcome_link.reason,
                member_event_id=outcome_link.event_id,
                outcome_group_id=outcome_link.outcome_id,
            )
        )
        _write_evidence_rows(session, {"narrative_link_id": link_id}, outcome_link.evidence)
    session.flush()
    session.flush()
