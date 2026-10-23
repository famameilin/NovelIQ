"诊断会话与报告共用的事件、包含及其他关系保存"

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.ids import new_id
from src.storage.models import (
    DIAGNOSIS_ROLES,
    Agent,
    CompleteEvent,
    NarrativeLink,
    SourceEvidence,
)
from src.storage.repositories import narrative_records as smap
from src.storage.repositories.narrative_records import write_evidence_rows as _write_evidence_rows
from src.storage.repositories.organization_writes import _require_report
from src.storage.repositories.queries import event_trees_organization as _org_queries


def _run_foreshadowing_actions(session, run_id):
    annotation_events = smap.run_annotation_event_ids(session, run_id)
    return (
        list(_org_queries.event_trees_organization_run_foreshadowing_actions_1(session, annotation_events))
        if annotation_events
        else []
    )


def _key(session, model, primary_key, **identity):
    row_id = session.scalar(
        select(getattr(model, primary_key)).where(*(getattr(model, name) == value for name, value in identity.items()))
    )
    return str(row_id) if row_id is not None else new_id()


def _write_evidence_rows_once(
    session: Session, owner: dict[str, Any], evidence: list[Any], *, existing: bool = False
) -> None:
    "同一所有者重投时核对完整有序证据"
    column, target = next(iter(owner.items()))
    rows = smap.fetch_evidence(session, getattr(SourceEvidence, column), [target]).get(target, [])
    if rows or existing:
        actual = [(row.paragraph_id, row.start_char, row.end_char, row.related_complete_event_id) for row in rows]
        incoming = [
            ref if isinstance(ref, dict) else vars(ref) if not hasattr(ref, "model_dump") else ref.model_dump()
            for ref in evidence
        ]
        wanted = [
            (ref["paragraph_id"], ref.get("char_start", 0), ref["char_end"], ref.get("event_id")) for ref in incoming
        ]
        if actual != wanted:
            raise ValueError(f"已保存证据与重投内容不一致: {column}={target}")
    else:
        _write_evidence_rows(session, owner, evidence)


def _existing_matches(session: Session, model: Any, identifier: str, expected: dict[str, Any]) -> bool:
    "同一身份的已保存内容必须与重投字段一致"
    row = session.get(model, identifier)
    if row is None:
        return False
    if any(getattr(row, field) != value for field, value in expected.items()):
        raise ValueError(f"已保存组织记录与重投内容不一致: {identifier}")
    return True


def _diagnosis_execution_ids(session: Session, run_id: str) -> list[str]:
    """本 run 诊断侧的会话与案例执行；只读写这些执行的行，不碰标注产物"""
    return list(session.scalars(select(Agent.id).where(Agent.run_id == run_id, Agent.type.in_(DIAGNOSIS_ROLES))))


def _evidence_event_refs(records: list[Any]) -> set[str]:
    "记录证据里引用的完整事件 id（证据行 related_complete_event_id 的外键面）"
    return {ref.event_id for item in records for ref in item.evidence if getattr(ref, "event_id", None) is not None}


def _referenced_event_ids(draft: Any, owned: set[str]) -> set[str]:
    "本生产者的包含、关系与证据引用到的事件身份"
    owned_events = [item for item in draft.events.values() if item.producer_agent_id in owned]
    owned_containments = [item for item in draft.containments.values() if item.producer_agent_id in owned]
    owned_relations = [item for item in draft.relations.values() if item.producer_agent_id in owned]
    referenced: set[str] = set()
    for edge in owned_containments:
        referenced.update((edge.parent_event_id, edge.child_event_id))
    for relation in owned_relations:
        referenced.update((relation.source_id, relation.target_id))
    for records in (owned_events, owned_containments, owned_relations):
        referenced.update(_evidence_event_refs(records))
    return referenced


def save_case_session_rows(session: Session, run_id: str, producer_agent_id: str, draft: Any) -> None:
    """按真实生产者幂等保存会话组织条目，不保存案例与结果的关联"""
    owned = {producer_agent_id}
    events = [item for item in draft.events.values() if item.producer_agent_id in owned]
    # 引用即固化：本批行引用到、尚未落库的草稿候选（可能由其他会话铸造）随本批一并落库，署名保持真实生产者
    referenced = sorted(_referenced_event_ids(draft, owned) - {item.event_id for item in events})
    existing = (
        set(
            session.scalars(
                select(CompleteEvent.event_id).where(
                    CompleteEvent.event_id.in_([item.event_id for item in events] + referenced)
                )
            )
        )
        if events or referenced
        else set()
    )
    for event_id in referenced:
        if event_id in existing:
            continue
        item = draft.events.get(event_id)
        if item is None:
            raise ValueError(f"被引用事件既不在草稿也不在库，无法落库: event_id={event_id}")
        events.append(item)
    if events:
        for item in events:
            if item.event_id in existing:
                smap.assert_event_matches(
                    session,
                    item.event_id,
                    {
                        field: getattr(item, field)
                        for field in (
                            "producer_agent_id",
                            "local_key",
                            "annotation_record_id",
                            "from_chapter_id",
                            "to_chapter_id",
                            "reason",
                            "title",
                            "problem",
                            "summary",
                            "event_type",
                            "status",
                            "progress",
                            "is_foreshadowing_root",
                            "payoff_likelihood",
                        )
                    },
                    item.evidence,
                )
                continue
            session.add(
                CompleteEvent(
                    event_id=item.event_id,
                    producer_agent_id=item.producer_agent_id,
                    local_key=item.local_key,
                    title=item.title,
                    reason=item.reason,
                    annotation_record_id=item.annotation_record_id,
                    from_chapter_id=item.from_chapter_id,
                    to_chapter_id=item.to_chapter_id,
                    is_foreshadowing_root=item.is_foreshadowing_root,
                    payoff_likelihood=item.payoff_likelihood,
                    problem=item.problem,
                    summary=item.summary,
                    event_type=item.event_type,
                    status=item.status,
                    progress=item.progress,
                )
            )
            _write_evidence_rows_once(session, {"complete_event_id": item.event_id}, item.evidence)
        session.flush()
    for edge in draft.containments.values():
        if edge.producer_agent_id not in owned:
            continue
        link_id = _key(
            session,
            NarrativeLink,
            "link_id",
            contained_parent_id=edge.parent_event_id,
            contained_child_id=edge.child_event_id,
        )
        if _existing_matches(
            session,
            NarrativeLink,
            link_id,
            {
                "producer_agent_id": edge.producer_agent_id,
                "reason": edge.reason,
                "contained_child_id": edge.child_event_id,
                "contained_parent_id": edge.parent_event_id,
            },
        ):
            _write_evidence_rows_once(session, {"narrative_link_id": link_id}, edge.evidence, existing=True)
            continue
        session.add(
            NarrativeLink(
                link_id=link_id,
                producer_agent_id=edge.producer_agent_id,
                reason=edge.reason,
                contained_child_id=edge.child_event_id,
                contained_parent_id=edge.parent_event_id,
            )
        )
        _write_evidence_rows_once(session, {"narrative_link_id": link_id}, edge.evidence)
    for relation in draft.relations.values():
        if relation.producer_agent_id not in owned:
            continue
        if _existing_matches(
            session,
            NarrativeLink,
            relation.relation_id,
            {
                "producer_agent_id": relation.producer_agent_id,
                "reason": relation.reason,
                "semantic_source_event_id": relation.source_id,
                "semantic_target_event_id": relation.target_id,
                "relation_type": relation.relation_type,
                "source_operation_local_key": relation.source_operation_id,
                "is_active": relation.is_active,
            },
        ):
            _write_evidence_rows_once(
                session, {"narrative_link_id": relation.relation_id}, relation.evidence, existing=True
            )
            continue
        session.add(
            NarrativeLink(
                link_id=relation.relation_id,
                producer_agent_id=relation.producer_agent_id,
                reason=relation.reason,
                semantic_source_event_id=relation.source_id,
                semantic_target_event_id=relation.target_id,
                relation_type=relation.relation_type,
                source_operation_local_key=relation.source_operation_id,
                is_active=relation.is_active,
            )
        )
        _write_evidence_rows_once(session, {"narrative_link_id": relation.relation_id}, relation.evidence)
    session.flush()
    session.flush()


def _session_executions(session: Session, agent_id: str) -> list[str]:
    """本诊断会话已登记的真实执行（用于情节推进来源校验）"""
    run_id = session.scalar(select(Agent.run_id).where(Agent.id == agent_id))
    if run_id is None:
        return []
    return list(session.scalars(select(Agent.id).where(Agent.run_id == run_id, Agent.type.in_(DIAGNOSIS_ROLES))))


def save_diagnosis_events(session: Session, run_id: str, organization: Any, report_id: str) -> None:
    """保存事件与组织贡献，重投时核对不可变内容"""
    agent_id = organization.source_agent_id
    if not agent_id:
        raise ValueError("事件保存缺少真实诊断会话身份")
    _require_report(session, run_id, report_id, agent_id)
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
            smap.assert_event_matches(
                session,
                item.event_id,
                {
                    field: getattr(item, field)
                    for field in (
                        "producer_agent_id",
                        "local_key",
                        "annotation_record_id",
                        "from_chapter_id",
                        "to_chapter_id",
                        "reason",
                        "title",
                        "problem",
                        "summary",
                        "event_type",
                        "status",
                        "progress",
                        "is_foreshadowing_root",
                        "payoff_likelihood",
                    )
                },
                item.evidence,
            )
            continue
        session.add(
            CompleteEvent(
                event_id=item.event_id,
                producer_agent_id=item.producer_agent_id,
                local_key=item.local_key,
                annotation_record_id=item.annotation_record_id,
                from_chapter_id=item.from_chapter_id,
                to_chapter_id=item.to_chapter_id,
                is_foreshadowing_root=item.is_foreshadowing_root,
                payoff_likelihood=item.payoff_likelihood,
                reason=item.reason,
                title=item.title,
                problem=item.problem,
                summary=item.summary,
                event_type=item.event_type,
                status=item.status,
                progress=item.progress,
            )
        )
        _write_evidence_rows_once(session, {"complete_event_id": item.event_id}, item.evidence)
    # 完整事件先落库，供事件归属的 event_id 外键引用
    session.flush()
    for edge in organization.containments:
        link_id = _key(
            session,
            NarrativeLink,
            "link_id",
            contained_parent_id=edge.parent_event_id,
            contained_child_id=edge.child_event_id,
        )
        if _existing_matches(
            session,
            NarrativeLink,
            link_id,
            {
                "producer_agent_id": edge.producer_agent_id,
                "reason": edge.reason,
                "contained_child_id": edge.child_event_id,
                "contained_parent_id": edge.parent_event_id,
            },
        ):
            _write_evidence_rows_once(session, {"narrative_link_id": link_id}, edge.evidence, existing=True)
            continue
        session.add(
            NarrativeLink(
                link_id=link_id,
                producer_agent_id=edge.producer_agent_id,
                reason=edge.reason,
                contained_child_id=edge.child_event_id,
                contained_parent_id=edge.parent_event_id,
            )
        )
        _write_evidence_rows_once(session, {"narrative_link_id": link_id}, edge.evidence)
    for relation in organization.relations:
        if _existing_matches(
            session,
            NarrativeLink,
            relation.relation_id,
            {
                "producer_agent_id": relation.producer_agent_id,
                "reason": relation.reason,
                "semantic_source_event_id": relation.source_id,
                "semantic_target_event_id": relation.target_id,
                "relation_type": relation.relation_type,
                "source_operation_local_key": relation.source_operation_id,
                "is_active": relation.is_active,
            },
        ):
            _write_evidence_rows_once(
                session, {"narrative_link_id": relation.relation_id}, relation.evidence, existing=True
            )
            continue
        session.add(
            NarrativeLink(
                link_id=relation.relation_id,
                producer_agent_id=relation.producer_agent_id,
                reason=relation.reason,
                semantic_source_event_id=relation.source_id,
                semantic_target_event_id=relation.target_id,
                relation_type=relation.relation_type,
                source_operation_local_key=relation.source_operation_id,
                # 新断言的真实活动状态；原始断言存在性不由本表重复表达
                is_active=relation.is_active,
            )
        )
        _write_evidence_rows_once(session, {"narrative_link_id": relation.relation_id}, relation.evidence)
    session.flush()
