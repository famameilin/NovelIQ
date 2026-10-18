"诊断事件、阶段、组织核对的物理保存"

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session as Storage

from src.storage.ids import new_id
from src.storage.models import CompleteEvent, EventRevision, NarrativeLink, OrganizationCheck
from src.storage.repositories import narrative_records as _records
from src.storage.repositories.narrative_records import write_evidence_rows as _write_evidence_rows
from src.storage.repositories.organization_writes import _require_report
from src.storage.repositories.queries import event_trees_diagnosis_persistence as _queries
from src.storage.repositories.queries import event_trees_organization as _org_queries


def _session_executions(session: Storage, session_id: str) -> list[str]:
    "本诊断会话已登记的真实执行（用于情节推进来源校验）"
    run_id = _queries.event_trees_diagnosis_persistence_session_executions_1(session, session_id)
    if run_id is None:
        return []
    return list(_queries.event_trees_diagnosis_persistence_session_executions_2(session, run_id))


def save_diagnosis_events(session: Storage, run_id: str, organization: Any, report_id: str) -> None:
    "只绑定本次原始来源，不更新旧结果、不在保存事务里推断语义"
    session_id = organization.source_execution_id
    if not session_id:
        raise ValueError("事件发布缺少真实诊断会话身份")
    _require_report(session, run_id, report_id, session_id)
    if _records.run_events(session, run_id):
        raise ValueError("本 run 已有发布事件；只允许重投同一冻结事务，不得改写或转换旧结果")
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
    session.flush()
    stage_declarations = sorted({declaration_id for item in organization.events for declaration_id in item.stage_order})
    if stage_declarations:
        (
            _records.run_declaration_ids(session, run_id).issuperset(stage_declarations)
            or (_ for _ in ()).throw(ValueError("事件阶段引用不属于本运行的声明"))
        )
    bindings: dict[str, str] = {}
    for item in organization.events:
        stages: list[str | None] = list(item.stage_order) if item.stage_order else [None]
        plan = [(new_id(), declaration_id) for declaration_id in stages]
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
        link_id = new_id()
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
                is_active=True,
            )
        )
        _write_evidence_rows(session, {"narrative_link_id": relation.relation_id}, relation.evidence)
    session.flush()
    _save_reviews(session, organization)
    _assert_foreshadowing_bound(session, run_id, bindings)
    _assert_fact_declarations_bound(session, session_id, bindings)
    session.flush()


def _save_reviews(session: Storage, organization: Any) -> None:
    "组织核对逐对象/逐对落库；同一对象只接受一个被接受判断"
    for event_review in organization.reviewed_events:
        session.add(
            OrganizationCheck(
                check_id=new_id(),
                producer_execution_id=event_review.producer_invocation_id,
                reason=event_review.reason,
                reviewed_event_id=event_review.event_id,
                snapshot_hash=event_review.snapshot_hash,
            )
        )
    for declaration_review in organization.declaration_reviews:
        session.add(
            OrganizationCheck(
                check_id=new_id(),
                producer_execution_id=declaration_review.producer_invocation_id,
                reason=declaration_review.reason,
                reviewed_declaration_id=declaration_review.declaration_id,
                snapshot_hash=declaration_review.source_hash,
            )
        )
    for comparison in organization.declaration_comparisons:
        for target_id in comparison.target_declaration_ids:
            check_id = new_id()
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
        check_id = new_id()
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


def _assert_foreshadowing_bound(session: Storage, run_id: str, bindings: dict[str, str]) -> None:
    "伏笔动作的来源/目标声明必须取得正式事件身份，未发布前保留声明身份不回填"
    for action in list(
        _org_queries.event_trees_organization_run_foreshadowing_actions_1(
            session, _records.run_declaration_ids(session, run_id)
        )
    ):
        if action.source_declaration_id not in bindings:
            raise ValueError("伏笔来源未得到完整事件身份确认")
        if action.target_declaration_id is not None and action.target_declaration_id not in bindings:
            raise ValueError("伏笔来源未得到完整事件身份确认")


def _assert_fact_declarations_bound(session: Storage, session_id: str, bindings: dict[str, str]) -> None:
    "情节推进经声明引用取得正式事件；没有绑定的声明不能被伪装成已发布事件"
    executions = _session_executions(session, session_id)
    if not executions:
        return
    declarations = set(_queries.event_trees_diagnosis_persistence_assert_fact_declarations_bound_1(session, executions))
    if declarations - set(bindings):
        raise ValueError("情节推进来源未得到完整事件身份确认")
