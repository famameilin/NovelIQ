"诊断会话与报告共用的事件、阶段及核对行保存"

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.ids import new_id
from src.storage.models import (
    DIAGNOSIS_ROLES,
    CompleteEvent,
    EventRevision,
    Execution,
    GraphFact,
    NarrativeLink,
    OrganizationCheck,
    SourceEvidence,
)
from src.storage.repositories import narrative_records as smap
from src.storage.repositories.narrative_records import write_evidence_rows as _write_evidence_rows
from src.storage.repositories.organization_writes import _require_report
from src.storage.repositories.queries import event_trees_organization as _org_queries


def _run_foreshadowing_actions(session, run_id):
    declarations = smap.run_declaration_ids(session, run_id)
    return (
        list(_org_queries.event_trees_organization_run_foreshadowing_actions_1(session, declarations))
        if declarations
        else []
    )


def _key(session, model, primary_key, **identity):
    row_id = session.scalar(
        select(getattr(model, primary_key)).where(*(getattr(model, name) == value for name, value in identity.items()))
    )
    return str(row_id) if row_id is not None else new_id()


def _write_evidence_rows_once(session: Session, owner: dict[str, Any], evidence: list[Any]) -> None:
    """证据行不重复写入：同一所有者已有证据时整批跳过（会话保存与报告保存共用）"""
    if not evidence:
        return
    column, target = next(iter(owner.items()))
    existing = session.scalar(
        select(SourceEvidence.evidence_id).where(getattr(SourceEvidence, column) == target).limit(1)
    )
    if existing is None:
        _write_evidence_rows(session, owner, evidence)


def _diagnosis_execution_ids(session: Session, run_id: str) -> list[str]:
    """本 run 诊断侧的会话与案例执行；只读写这些执行的行，不碰标注产物"""
    return list(
        session.scalars(
            select(Execution.execution_id).where(Execution.run_id == run_id, Execution.role.in_(DIAGNOSIS_ROLES))
        )
    )


def save_case_session_rows(session: Session, run_id: str, case_ids: set[str], draft: Any) -> None:
    """案例会话做完保存一次：该会话产出的组织条目按正式行形状入库，键与报告保存完全相同

    无报告、不跑整轮断言；报告保存时同键行只补缺不改写（save_diagnosis_events 幂等）。
    会话按 producer 归属，条目按 source_case_id 归属，均已随写入确定。
    """
    owned = {case_id for case_id in case_ids if case_id}
    if not owned:
        return
    events = [item for item in draft.events.values() if item.source_case_id in owned]
    if events:
        existing = set(
            session.scalars(
                select(CompleteEvent.event_id).where(CompleteEvent.event_id.in_([item.event_id for item in events]))
            )
        )
        for item in events:
            if item.event_id in existing:
                continue
            session.add(
                CompleteEvent(
                    event_id=item.event_id,
                    producer_execution_id=item.producer_invocation_id,
                    local_key=item.local_key,
                    identity_reason=item.reason,
                )
            )
            _write_evidence_rows_once(session, {"complete_event_id": item.event_id}, item.evidence)
        session.flush()
        for item in events:
            if item.event_id in existing:
                continue
            stages: list[str | None] = list(item.stage_order) if item.stage_order else [None]
            for stage_index, declaration_id in enumerate(stages):
                revision_id = _key(
                    session, EventRevision, "revision_id", event_id=item.event_id, declaration_id=declaration_id
                )
                if declaration_id is not None:
                    session.add(
                        EventRevision(
                            revision_id=revision_id,
                            event_id=item.event_id,
                            stage_index=stage_index,
                            declaration_id=declaration_id,
                        )
                    )
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
    for edge in draft.containments.values():
        if edge.source_case_id not in owned:
            continue
        link_id = _key(
            session,
            NarrativeLink,
            "link_id",
            contained_parent_id=edge.parent_event_id,
            contained_child_id=edge.child_event_id,
        )
        if session.get(NarrativeLink, link_id) is not None:
            continue
        session.add(
            NarrativeLink(
                link_id=link_id,
                producer_execution_id=edge.producer_invocation_id,
                reason=edge.reason,
                contained_child_id=edge.child_event_id,
                contained_parent_id=edge.parent_event_id,
            )
        )
        _write_evidence_rows_once(session, {"narrative_link_id": link_id}, edge.evidence)
    for relation in draft.relations.values():
        if relation.source_case_id not in owned:
            continue
        if session.get(NarrativeLink, relation.relation_id) is not None:
            continue
        session.add(
            NarrativeLink(
                link_id=relation.relation_id,
                producer_execution_id=relation.producer_invocation_id,
                reason=relation.reason,
                semantic_source_event_id=relation.source_id,
                semantic_target_event_id=relation.target_id,
                relation_type=relation.relation_type,
                source_operation_local_key=relation.source_operation_id,
                is_active=True,
            )
        )
        _write_evidence_rows_once(session, {"narrative_link_id": relation.relation_id}, relation.evidence)
    session.flush()
    _save_session_checks(session, owned, draft)
    session.flush()


def _save_session_checks(session: Session, owned: set[str], draft: Any) -> None:
    """会话产出的四类核对行（单事件/单声明/声明对/事件对）；已存在不改写"""
    for event_review in draft.reviewed_events.values():
        if event_review.source_case_id not in owned:
            continue
        check_id = _key(session, OrganizationCheck, "check_id", reviewed_event_id=event_review.event_id)
        if session.get(OrganizationCheck, check_id) is not None:
            continue
        session.add(
            OrganizationCheck(
                check_id=check_id,
                producer_execution_id=event_review.producer_invocation_id,
                reason=event_review.reason,
                reviewed_event_id=event_review.event_id,
                snapshot_hash=event_review.snapshot_hash,
            )
        )
    for declaration_review in draft.declaration_reviews.values():
        if declaration_review.source_case_id not in owned:
            continue
        check_id = _key(
            session, OrganizationCheck, "check_id", reviewed_declaration_id=declaration_review.declaration_id
        )
        if session.get(OrganizationCheck, check_id) is not None:
            continue
        session.add(
            OrganizationCheck(
                check_id=check_id,
                producer_execution_id=declaration_review.producer_invocation_id,
                reason=declaration_review.reason,
                reviewed_declaration_id=declaration_review.declaration_id,
                snapshot_hash=declaration_review.source_hash,
            )
        )
    for comparison in draft.declaration_comparisons.values():
        if comparison.source_case_id not in owned:
            continue
        for target_id in comparison.target_declaration_ids:
            check_id = _key(
                session,
                OrganizationCheck,
                "check_id",
                source_declaration_id=comparison.source_declaration_id,
                target_declaration_id=target_id,
            )
            if session.get(OrganizationCheck, check_id) is not None:
                continue
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
            _write_evidence_rows_once(session, {"check_id": check_id}, comparison.evidence)
    for structure_review in draft.structure_reviews.values():
        if structure_review.source_case_id not in owned:
            continue
        check_id = _key(
            session,
            OrganizationCheck,
            "check_id",
            source_event_id=structure_review.source_event_id,
            target_event_id=structure_review.target_event_id,
        )
        if session.get(OrganizationCheck, check_id) is not None:
            continue
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
        _write_evidence_rows_once(session, {"check_id": check_id}, structure_review.evidence)


def _session_executions(session: Session, session_id: str) -> list[str]:
    """本诊断会话已登记的真实执行（用于情节推进来源校验）"""
    run_id = session.scalar(select(Execution.session_run_id).where(Execution.execution_id == session_id))
    if run_id is None:
        return []
    return list(
        session.scalars(
            select(Execution.execution_id).where(Execution.run_id == run_id, Execution.role.in_(DIAGNOSIS_ROLES))
        )
    )


def save_diagnosis_events(session: Session, run_id: str, organization: Any, report_id: str) -> None:
    """只绑定本次原始来源，不更新旧结果、不在保存事务里推断语义"""
    session_id = organization.source_execution_id
    if not session_id:
        raise ValueError("事件保存缺少真实诊断会话身份")
    _require_report(session, run_id, report_id, session_id)
    # 会话保存（每个会话做完保存一次）可能已写入同 ID 行：重投只补缺，不改写既有行
    existing_events = (
        set(
            session.scalars(
                select(CompleteEvent.event_id).where(
                    CompleteEvent.event_id.in_([item.event_id for item in organization.events])
                )
            )
        )
        if organization.events
        else set()
    )
    for item in organization.events:
        if item.event_id in existing_events:
            continue
        session.add(
            CompleteEvent(
                event_id=item.event_id,
                producer_execution_id=item.producer_invocation_id,
                local_key=item.local_key,
                identity_reason=item.reason,
            )
        )
        _write_evidence_rows_once(session, {"complete_event_id": item.event_id}, item.evidence)
    # 阶段行先落库：event_id 外键不靠 ORM 表排序保证
    session.flush()
    stage_declarations = sorted({declaration_id for item in organization.events for declaration_id in item.stage_order})
    if stage_declarations:
        # 阶段来源必须是本 run 的不可变声明；来源身份从不解释为正式事件身份
        if not set(stage_declarations) <= smap.run_declaration_ids(session, run_id):
            raise ValueError("事件阶段引用不属于本运行的声明")
    bindings: dict[str, str] = {}
    for item in organization.events:
        # 顺序由模型明确提交；绝不按章号或最后写入时间选取事实发生顺序
        stages: list[str | None] = list(item.stage_order) if item.stage_order else [None]
        plan = [
            (
                _key(session, EventRevision, "revision_id", event_id=item.event_id, declaration_id=declaration_id),
                declaration_id,
            )
            for declaration_id in stages
        ]
        for stage_index, (revision_id, declaration_id) in enumerate(plan):
            if declaration_id is not None:
                bindings[declaration_id] = item.event_id
                if session.get(EventRevision, revision_id) is not None:
                    continue
                session.add(
                    EventRevision(
                        revision_id=revision_id,
                        event_id=item.event_id,
                        stage_index=stage_index,
                        declaration_id=declaration_id,
                    )
                )
            else:
                if session.get(EventRevision, revision_id) is not None:
                    continue
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
        link_id = _key(
            session,
            NarrativeLink,
            "link_id",
            contained_parent_id=edge.parent_event_id,
            contained_child_id=edge.child_event_id,
        )
        if session.get(NarrativeLink, link_id) is not None:
            continue
        session.add(
            NarrativeLink(
                link_id=link_id,
                producer_execution_id=edge.producer_invocation_id,
                reason=edge.reason,
                contained_child_id=edge.child_event_id,
                contained_parent_id=edge.parent_event_id,
            )
        )
        _write_evidence_rows_once(session, {"narrative_link_id": link_id}, edge.evidence)
    for relation in organization.relations:
        if session.get(NarrativeLink, relation.relation_id) is not None:
            continue
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
        _write_evidence_rows_once(session, {"narrative_link_id": relation.relation_id}, relation.evidence)
    session.flush()
    _save_reviews(session, organization)
    _assert_foreshadowing_bound(session, run_id, bindings)
    _assert_fact_declarations_bound(session, session_id, bindings)
    session.flush()


def _save_reviews(session: Session, organization: Any) -> None:
    """组织核对逐对象/逐对落库；同一对象只接受一个被接受判断；已存在的行不改写"""
    for event_review in organization.reviewed_events:
        check_id = _key(session, OrganizationCheck, "check_id", reviewed_event_id=event_review.event_id)
        if session.get(OrganizationCheck, check_id) is not None:
            continue
        session.add(
            OrganizationCheck(
                check_id=check_id,
                producer_execution_id=event_review.producer_invocation_id,
                reason=event_review.reason,
                reviewed_event_id=event_review.event_id,
                snapshot_hash=event_review.snapshot_hash,
            )
        )
    for declaration_review in organization.declaration_reviews:
        check_id = _key(
            session, OrganizationCheck, "check_id", reviewed_declaration_id=declaration_review.declaration_id
        )
        if session.get(OrganizationCheck, check_id) is not None:
            continue
        session.add(
            OrganizationCheck(
                check_id=check_id,
                producer_execution_id=declaration_review.producer_invocation_id,
                reason=declaration_review.reason,
                reviewed_declaration_id=declaration_review.declaration_id,
                snapshot_hash=declaration_review.source_hash,
            )
        )
    for comparison in organization.declaration_comparisons:
        for target_id in comparison.target_declaration_ids:
            check_id = _key(
                session,
                OrganizationCheck,
                "check_id",
                source_declaration_id=comparison.source_declaration_id,
                target_declaration_id=target_id,
            )
            if session.get(OrganizationCheck, check_id) is not None:
                continue
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
            _write_evidence_rows_once(session, {"check_id": check_id}, comparison.evidence)
    for structure_review in organization.structure_reviews:
        check_id = _key(
            session,
            OrganizationCheck,
            "check_id",
            source_event_id=structure_review.source_event_id,
            target_event_id=structure_review.target_event_id,
        )
        if session.get(OrganizationCheck, check_id) is not None:
            continue
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
        _write_evidence_rows_once(session, {"check_id": check_id}, structure_review.evidence)
    session.flush()


def _assert_foreshadowing_bound(session: Session, run_id: str, bindings: dict[str, str]) -> None:
    """伏笔动作的来源/目标声明必须取得正式事件身份，未绑定前保留声明身份不回填"""
    for action in _run_foreshadowing_actions(session, run_id):
        if action.source_declaration_id not in bindings:
            raise ValueError("伏笔来源未得到完整事件身份确认")
        if action.target_declaration_id is not None and action.target_declaration_id not in bindings:
            raise ValueError("伏笔来源未得到完整事件身份确认")


def _assert_fact_declarations_bound(session: Session, session_id: str, bindings: dict[str, str]) -> None:
    """情节推进经声明引用取得正式事件；没有绑定的声明不能被伪装成正式事件"""
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
