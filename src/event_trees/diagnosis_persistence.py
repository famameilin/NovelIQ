"""将冻结诊断候选一次发布到新关系，源声明保持不可变（2026-10-16 全库 3NF 改造）

- 完整事件：complete_events（身份 + 真实生产者 + 同一性理由）
- 阶段版本：event_revisions 的显式连续 stage_index 链（绑定声明或独立 origin 正文恰一）
- 包含/关系：narrative_links 的单父包含形状与语义关系形状，证据进 source_evidence
- 组织核对：organization_checks 的单事件/单声明核对与声明对/结构对判断四类形状
伏笔 root/target 不在此回填：正式读取经阶段声明绑定投影；情节推进同样经声明引用读取。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.models import (
    CompleteEvent,
    EventRevision,
    Execution,
    GraphFact,
    NarrativeLink,
    OrganizationCheck,
    WorkItem,
)
from src.utils.identity import stable_uuid

from .organization import (
    EventOrganizationDraft,
    NarrativeOrganization,
    _require_report,
    _run_events,
    _run_foreshadowing_actions,
    _write_evidence_rows,
    validate_organization,
)


def _session_executions(session: Session, session_id: str) -> list[str]:
    """本诊断会话已登记的真实执行（用于情节推进来源校验）"""
    return list(
        session.scalars(
            select(Execution.execution_id).where(
                Execution.work_id.in_(
                    select(WorkItem.work_id).where(WorkItem.diagnosis_session_id == session_id)
                )
            )
        )
    )


def save_diagnosis_events(session: Session, run_id: str, organization: NarrativeOrganization, report_id: str) -> None:
    """只绑定本次原始来源，不更新旧结果、不在保存事务里推断语义"""
    session_id = organization.source_execution_id
    if not session_id:
        raise ValueError("事件发布缺少真实诊断会话身份")
    _require_report(session, run_id, report_id, session_id)
    if _run_events(session, run_id):
        raise ValueError("本 run 已有发布事件；只允许重投同一冻结事务，不得改写或转换旧结果")
    validate_organization(session, run_id, organization)
    for item in organization.events:
        session.add(
            CompleteEvent(
                event_id=item.event_id,
                producer_execution_id=item.producer_invocation_id,
                local_key=item.local_key,
                identity_reason=item.reason,
            )
        )
        _write_evidence_rows(session, {"complete_event_id": item.event_id}, item.evidence)
    # 阶段行先落库：event_id 外键不靠 ORM 表排序保证
    session.flush()
    stage_declarations = sorted(
        {declaration_id for item in organization.events for declaration_id in item.stage_order}
    )
    if stage_declarations:
        # 阶段来源必须是本 run 的不可变声明；来源身份从不解释为已发布的事件身份
        EventOrganizationDraft(session, run_id).read_declarations(stage_declarations)
    bindings: dict[str, str] = {}
    for item in organization.events:
        # 顺序由模型明确提交；绝不按章号或最后写入时间选取事实发生顺序
        stages: list[str | None] = list(item.stage_order) if item.stage_order else [None]
        plan = [
            (stable_uuid(run_id, "event_stage", item.event_id, declaration_id or "origin"), declaration_id)
            for declaration_id in stages
        ]
        for stage_index, (revision_id, declaration_id) in enumerate(plan):
            if declaration_id is not None:
                session.add(
                    EventRevision(
                        revision_id=revision_id,
                        event_id=item.event_id,
                        stage_index=stage_index,
                        declaration_id=declaration_id,
                    )
                )
                bindings[declaration_id] = item.event_id
            else:
                session.add(
                    EventRevision(
                        revision_id=revision_id,
                        event_id=item.event_id,
                        stage_index=stage_index,
                        origin_title=item.title,
                        origin_problem=item.problem,
                        origin_summary=item.summary,
                        origin_event_type=item.event_type,
                        origin_status=item.status,
                        origin_progress=item.progress,
                    )
                )
        session.flush()
    for edge in organization.containments:
        link_id = stable_uuid("event_containment", edge.parent_event_id, edge.child_event_id)
        session.add(
            NarrativeLink(
                link_id=link_id,
                producer_execution_id=edge.producer_invocation_id,
                reason=edge.reason,
                contained_child_id=edge.child_event_id,
                contained_parent_id=edge.parent_event_id,
            )
        )
        _write_evidence_rows(session, {"narrative_link_id": link_id}, edge.evidence)
    for relation in organization.relations:
        session.add(
            NarrativeLink(
                link_id=relation.relation_id,
                producer_execution_id=relation.producer_invocation_id,
                reason=relation.reason,
                semantic_source_event_id=relation.source_id,
                semantic_target_event_id=relation.target_id,
                relation_type=relation.relation_type,
                source_operation_local_key=relation.source_operation_id,
                # 新断言的真实活动状态；原始断言存在性不由本表重复表达
                is_active=True,
            )
        )
        _write_evidence_rows(session, {"narrative_link_id": relation.relation_id}, relation.evidence)
    session.flush()
    _save_reviews(session, organization)
    _assert_foreshadowing_bound(session, run_id, bindings)
    _assert_fact_declarations_bound(session, session_id, bindings)
    session.flush()


def _save_reviews(session: Session, organization: NarrativeOrganization) -> None:
    """组织核对逐对象/逐对落库；同一对象只接受一个被接受判断"""
    for event_review in organization.reviewed_events:
        session.add(
            OrganizationCheck(
                check_id=stable_uuid("organization_check_event", event_review.event_id),
                producer_execution_id=event_review.producer_invocation_id,
                reason=event_review.reason,
                reviewed_event_id=event_review.event_id,
                snapshot_hash=event_review.snapshot_hash,
            )
        )
    for declaration_review in organization.declaration_reviews:
        session.add(
            OrganizationCheck(
                check_id=stable_uuid("organization_check_declaration", declaration_review.declaration_id),
                producer_execution_id=declaration_review.producer_invocation_id,
                reason=declaration_review.reason,
                reviewed_declaration_id=declaration_review.declaration_id,
                snapshot_hash=declaration_review.source_hash,
            )
        )
    for comparison in organization.declaration_comparisons:
        for target_id in comparison.target_declaration_ids:
            check_id = stable_uuid(
                "organization_check_declaration_pair", comparison.source_declaration_id, target_id
            )
            session.add(
                OrganizationCheck(
                    check_id=check_id,
                    producer_execution_id=comparison.producer_invocation_id,
                    reason=comparison.reason,
                    source_declaration_id=comparison.source_declaration_id,
                    target_declaration_id=target_id,
                    disposition=comparison.disposition,
                )
            )
            _write_evidence_rows(session, {"check_id": check_id}, comparison.evidence)
    for structure_review in organization.structure_reviews:
        check_id = stable_uuid(
            "organization_check_event_pair", structure_review.source_event_id, structure_review.target_event_id
        )
        session.add(
            OrganizationCheck(
                check_id=check_id,
                producer_execution_id=structure_review.producer_invocation_id,
                reason=structure_review.reason,
                source_event_id=structure_review.source_event_id,
                target_event_id=structure_review.target_event_id,
                disposition=structure_review.disposition,
                snapshot_hash=structure_review.snapshot_hash,
            )
        )
        _write_evidence_rows(session, {"check_id": check_id}, structure_review.evidence)
    session.flush()


def _assert_foreshadowing_bound(session: Session, run_id: str, bindings: dict[str, str]) -> None:
    """伏笔动作的来源/目标声明必须取得正式事件身份，未发布前保留声明身份不回填"""
    for action in _run_foreshadowing_actions(session, run_id):
        if action.source_declaration_id not in bindings:
            raise ValueError("伏笔来源未得到完整事件身份确认")
        if action.target_declaration_id is not None and action.target_declaration_id not in bindings:
            raise ValueError("伏笔来源未得到完整事件身份确认")


def _assert_fact_declarations_bound(session: Session, session_id: str, bindings: dict[str, str]) -> None:
    """情节推进经声明引用取得正式事件；没有绑定的声明不能被伪装成已发布事件"""
    executions = _session_executions(session, session_id)
    if not executions:
        return
    declarations = set(
        session.scalars(
            select(GraphFact.declaration_id).where(
                GraphFact.direct_producer_execution_id.in_(executions),
                GraphFact.declaration_id.is_not(None),
            )
        )
    )
    if declarations - set(bindings):
        raise ValueError("情节推进来源未得到完整事件身份确认")
