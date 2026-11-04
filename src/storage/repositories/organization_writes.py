"诊断正式组织的物理保存；领域验证由发布前的正式业务链完成"

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session as Storage

from src.storage.models import NarrativeGroup
from src.storage.repositories.narrative_records import write_evidence_rows as _write_evidence_rows
from src.storage.repositories.queries import organization_rows as _org_queries


def _require_report(session: Storage, run_id: str, report_id: str, agent_id: str | None) -> Any:
    "正式组织必须与本次诊断会话的报告一同保存，不接受其他产物冒充"
    report = _org_queries.get_report(session, report_id)
    if report is None:
        raise ValueError("全书组织必须与本任务诊断报告一同保存")
    owner = _org_queries.get_report_owner(session, report)
    if owner is None or owner.run_id != run_id:
        raise ValueError("诊断报告不属于本运行")
    if agent_id is not None and report.agent_id != agent_id:
        raise ValueError("诊断报告与本次诊断会话不一致")
    return report


def save_organization(session: Storage, run_id: str, organization: Any, report_id: str) -> None:
    "与诊断报告共用调用方事务，只发布本 run 的结果及事件贡献"
    _require_report(session, run_id, report_id, organization.source_agent_id)
    if list(_org_queries.list_published_group_ids(session, run_id)):
        raise ValueError("叙事组织已发布，禁止替换旧运行产物")
    for item in organization.outcomes:
        session.add(
            NarrativeGroup(
                group_id=item.outcome_id,
                producer_agent_id=item.producer_agent_id,
                kind="outcome",
                title=item.title,
                description=item.description,
                is_event_line=False,
                tree_key=None,
            )
        )
    session.flush()
    for item in organization.outcomes:
        _write_evidence_rows(session, {"narrative_group_id": item.outcome_id}, item.evidence)
    session.flush()
