"""将诊断候选按正式行形状保存到库，源声明保持不可变

- 完整事件：complete_events（身份 + 真实生产者 + 同一性理由）
- 阶段版本：event_revisions 的显式连续 stage_index 链（绑定声明或独立 origin 正文恰一）
- 包含/关系：narrative_links 的单父包含形状与语义关系形状，证据进 source_evidence
- 组织核对：organization_checks 的单事件/单声明核对与声明对/结构对判断四类形状
伏笔 root/target 不在此回填：正式读取经阶段声明绑定投影；情节推进同样经声明引用读取。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

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
from src.utils.identity import stable_uuid

from . import storage_map as smap
from .organization import (
    BoundOrganizationEvidence,
    CompleteEventDraft,
    ContainmentDraft,
    DeclarationComparisonDraft,
    DeclarationReviewDraft,
    EventOrganizationDraft,
    EventReviewDraft,
    NarrativeOrganization,
    RelationDraft,
    StructureReviewDraft,
    _evidence_payloads,
    _require_report,
    _run_event_dicts,
    _run_events,
    _run_foreshadowing_actions,
    _write_evidence_rows,
    validate_organization,
)


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
            select(Execution.execution_id).where(
                Execution.run_id == run_id, Execution.role.in_(DIAGNOSIS_ROLES)
            )
        )
    )


def save_case_session_rows(
    session: Session, run_id: str, case_ids: set[str], draft: EventOrganizationDraft
) -> None:
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
                revision_id = stable_uuid(run_id, "event_stage", item.event_id, declaration_id or "origin")
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
        link_id = stable_uuid("event_containment", edge.parent_event_id, edge.child_event_id)
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


def _save_session_checks(session: Session, owned: set[str], draft: EventOrganizationDraft) -> None:
    """会话产出的四类核对行（单事件/单声明/声明对/事件对）；已存在不改写"""
    for event_review in draft.reviewed_events.values():
        if event_review.source_case_id not in owned:
            continue
        check_id = stable_uuid("organization_check_event", event_review.event_id)
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
        check_id = stable_uuid("organization_check_declaration", declaration_review.declaration_id)
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
            check_id = stable_uuid(
                "organization_check_declaration_pair", comparison.source_declaration_id, target_id
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
        check_id = stable_uuid(
            "organization_check_event_pair", structure_review.source_event_id, structure_review.target_event_id
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


def _checked_disposition(value: str | None, allowed: tuple[str, ...]) -> Any:
    """水合核对行时只接受既有对判取值，未知取值直接拒绝"""
    if value not in allowed:
        raise ValueError(f"组织核对行的对判取值不受支持: {value!r}")
    return value


def hydrate_draft_from_run(session: Session, run_id: str, draft: EventOrganizationDraft) -> None:
    """把本 run 已保存的行水合进草稿内存：续跑在既有成果上继续

    行是会话保存留下的正式形状行；保存随后按完整内存状态计算快照。
    """
    rows = _run_events(session, run_id)
    if not rows:
        return
    dicts = _run_event_dicts(session, run_id)
    chains = smap.stage_chain(session, list(rows))
    declarations = draft._declarations()
    # Result 带 keys() 会被 dict() 当映射做下标取值后报错，只能逐行展开
    anchors: dict[str, Any] = {}
    for execution_id, case_anchor in session.execute(
        select(Execution.execution_id, Execution.case_anchor).where(
            Execution.run_id == run_id, Execution.case_anchor.is_not(None)
        )
    ):
        anchors[execution_id] = case_anchor
    event_evidence = smap.fetch_evidence(session, SourceEvidence.complete_event_id, list(rows))
    for event_id, row in rows.items():
        data = dicts[event_id]
        stages = chains.get(event_id) or []
        stage_order = [item.declaration_id for item in stages if item.declaration_id is not None]
        payloads = _evidence_payloads(session, run_id, event_evidence.get(event_id, []))
        draft.events[event_id] = CompleteEventDraft(
            event_id=event_id,
            local_key=row.local_key,
            title=data["title"],
            problem=data["problem"],
            summary=data["summary"],
            event_type=data["event_type"],
            status=data["status"],
            progress=data["progress"],
            declaration_ids=list(stage_order),
            stage_order=stage_order,
            current_declaration_id=stage_order[-1] if stage_order else None,
            reason=row.identity_reason,
            source_hashes={
                declaration: declarations[declaration]["source_hash"]
                for declaration in stage_order
                if declaration in declarations
            },
            first_text_position=data["first_text_position"],
            evidence=[BoundOrganizationEvidence(**payload) for payload in payloads],
            source_case_id=anchors.get(row.producer_execution_id, ""),
            producer_invocation_id=row.producer_execution_id,
        )
    executions = _diagnosis_execution_ids(session, run_id)
    if not executions:
        return
    link_rows = list(
        session.scalars(select(NarrativeLink).where(NarrativeLink.producer_execution_id.in_(executions)))
    )
    link_evidence = smap.fetch_evidence(
        session, SourceEvidence.narrative_link_id, [row.link_id for row in link_rows]
    )
    for link in link_rows:
        bound = [
            BoundOrganizationEvidence(**payload)
            for payload in _evidence_payloads(session, run_id, link_evidence.get(link.link_id, []))
        ]
        if link.contained_child_id is not None and link.contained_parent_id is not None:
            draft.containments[(link.contained_parent_id, link.contained_child_id)] = ContainmentDraft(
                parent_event_id=link.contained_parent_id,
                child_event_id=link.contained_child_id,
                reason=link.reason,
                evidence=bound,
                source_case_id=anchors.get(link.producer_execution_id, ""),
                producer_invocation_id=link.producer_execution_id,
            )
        elif link.semantic_source_event_id is not None and link.semantic_target_event_id is not None:
            draft.relations[link.link_id] = RelationDraft(
                relation_id=link.link_id,
                source_kind="event",
                source_id=link.semantic_source_event_id,
                target_kind="event",
                target_id=link.semantic_target_event_id,
                relation_type=link.relation_type or "",
                reason=link.reason,
                source_operation_id=link.source_operation_local_key or "",
                evidence=bound,
                source_case_id=anchors.get(link.producer_execution_id, ""),
                producer_invocation_id=link.producer_execution_id,
            )
    check_rows = list(
        session.scalars(
            select(OrganizationCheck).where(OrganizationCheck.producer_execution_id.in_(executions))
        )
    )
    check_evidence = smap.fetch_evidence(session, SourceEvidence.check_id, [row.check_id for row in check_rows])
    for check in check_rows:
        bound_check = [
            BoundOrganizationEvidence(**payload)
            for payload in _evidence_payloads(session, run_id, check_evidence.get(check.check_id, []))
        ]
        if check.reviewed_event_id is not None:
            draft.reviewed_events[check.reviewed_event_id] = EventReviewDraft(
                event_id=check.reviewed_event_id,
                reason=check.reason,
                snapshot_hash=check.snapshot_hash or "",
                source_case_id=anchors.get(check.producer_execution_id, ""),
                producer_invocation_id=check.producer_execution_id,
            )
        elif check.reviewed_declaration_id is not None:
            draft.declaration_reviews[check.reviewed_declaration_id] = DeclarationReviewDraft(
                declaration_id=check.reviewed_declaration_id,
                source_hash=check.snapshot_hash or "",
                reason=check.reason,
                source_case_id=anchors.get(check.producer_execution_id, ""),
                producer_invocation_id=check.producer_execution_id,
            )
        elif check.source_declaration_id is not None and check.target_declaration_id is not None:
            draft.declaration_comparisons[(check.source_declaration_id, check.target_declaration_id)] = (
                DeclarationComparisonDraft(
                    source_declaration_id=check.source_declaration_id,
                    target_declaration_ids=[check.target_declaration_id],
                    disposition=_checked_disposition(
                        check.disposition, ("same_event", "independent", "related")
                    ),
                    reason=check.reason,
                    evidence=bound_check,
                    source_case_id=anchors.get(check.producer_execution_id, ""),
                    producer_invocation_id=check.producer_execution_id,
                )
            )
        elif check.source_event_id is not None and check.target_event_id is not None:
            key = (
                min(check.source_event_id, check.target_event_id),
                max(check.source_event_id, check.target_event_id),
            )
            draft.structure_reviews[key] = StructureReviewDraft(
                source_event_id=check.source_event_id,
                target_event_id=check.target_event_id,
                disposition=_checked_disposition(
                    check.disposition, ("contains", "part_of", "related", "independent")
                ),
                reason=check.reason,
                snapshot_hash=check.snapshot_hash or "",
                evidence=bound_check,
                source_case_id=anchors.get(check.producer_execution_id, ""),
                producer_invocation_id=check.producer_execution_id,
            )


def _session_executions(session: Session, session_id: str) -> list[str]:
    """本诊断会话已登记的真实执行（用于情节推进来源校验）"""
    run_id = session.scalar(select(Execution.session_run_id).where(Execution.execution_id == session_id))
    if run_id is None:
        return []
    return list(
        session.scalars(
            select(Execution.execution_id).where(
                Execution.run_id == run_id, Execution.role.in_(DIAGNOSIS_ROLES)
            )
        )
    )


def save_diagnosis_events(session: Session, run_id: str, organization: NarrativeOrganization, report_id: str) -> None:
    """只绑定本次原始来源，不更新旧结果、不在保存事务里推断语义"""
    session_id = organization.source_execution_id
    if not session_id:
        raise ValueError("事件保存缺少真实诊断会话身份")
    _require_report(session, run_id, report_id, session_id)
    validate_organization(session, run_id, organization)
    # 会话保存（每个会话做完保存一次）可能已写入同 ID 行：重投只补缺，不改写既有行
    existing_events = set(
        session.scalars(
            select(CompleteEvent.event_id).where(
                CompleteEvent.event_id.in_([item.event_id for item in organization.events])
            )
        )
    ) if organization.events else set()
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
    stage_declarations = sorted(
        {declaration_id for item in organization.events for declaration_id in item.stage_order}
    )
    if stage_declarations:
        # 阶段来源必须是本 run 的不可变声明；来源身份从不解释为正式事件身份
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
        link_id = stable_uuid("event_containment", edge.parent_event_id, edge.child_event_id)
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


def _save_reviews(session: Session, organization: NarrativeOrganization) -> None:
    """组织核对逐对象/逐对落库；同一对象只接受一个被接受判断；已存在的行不改写"""
    for event_review in organization.reviewed_events:
        check_id = stable_uuid("organization_check_event", event_review.event_id)
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
        check_id = stable_uuid("organization_check_declaration", declaration_review.declaration_id)
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
            check_id = stable_uuid(
                "organization_check_declaration_pair", comparison.source_declaration_id, target_id
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
        check_id = stable_uuid(
            "organization_check_event_pair", structure_review.source_event_id, structure_review.target_event_id
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
