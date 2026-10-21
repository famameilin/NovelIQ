"按当前运行已保存的事件与核对记录恢复诊断草稿"

from __future__ import annotations

from typing import Any, Literal, cast

from src.storage import Storage

from . import storage_map as smap
from .organization import (
    BoundOrganizationEvidence,
    CompleteEventDraft,
    ContainmentDraft,
    EventOrganizationDraft,
    EventReviewDraft,
    RelationDraft,
    StructureReviewDraft,
    _evidence_payloads,
    _run_event_dicts,
    _run_events,
)


def _checked_disposition(value: str | None, allowed: tuple[str, ...]) -> Any:
    """水合核对行时只接受既有对判取值，未知取值直接拒绝"""
    if value not in allowed:
        raise ValueError(f"组织核对行的对判取值不受支持: {value!r}")
    return value


def hydrate_draft_from_run(session: Storage, run_id: str, draft: EventOrganizationDraft) -> None:
    """把本 run 已保存的行水合进草稿内存：续跑在既有成果上继续

    行是会话保存留下的正式形状行；保存随后按完整内存状态计算快照。
    """
    rows = _run_events(session, run_id)
    if not rows:
        return
    dicts = _run_event_dicts(session, run_id)
    snapshot = session.diagnosis.session_rows(run_id)
    event_evidence = smap.fetch_evidence(session, "complete_event_id", list(rows))
    for event_id, row in rows.items():
        data = dicts[event_id]
        payloads = _evidence_payloads(session, run_id, event_evidence.get(event_id, []))
        draft.events[event_id] = CompleteEventDraft(
            event_id=event_id,
            local_key=row.local_key,
            title=row.title,
            problem=row.problem,
            summary=row.summary,
            event_type=row.event_type,
            status=cast(Literal["ongoing", "resolved"], row.status),
            progress=row.progress,
            reason=row.reason,
            annotation_record_id=row.annotation_record_id,
            from_chapter_id=row.from_chapter_id,
            to_chapter_id=row.to_chapter_id,
            is_foreshadowing_root=row.is_foreshadowing_root,
            payoff_likelihood=row.payoff_likelihood,
            first_text_position=data["first_text_position"],
            evidence=[BoundOrganizationEvidence(**payload) for payload in payloads],
            producer_agent_id=row.producer_agent_id,
            participants=data["participants"],
        )
    link_rows = snapshot["links"]
    link_evidence = smap.fetch_evidence(session, "narrative_link_id", [row.link_id for row in link_rows])
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
                producer_agent_id=link.producer_agent_id,
            )
        elif link.semantic_source_event_id is not None and link.semantic_target_event_id is not None:
            draft.saved_relation_ids.add(link.link_id)
            draft.relations[link.link_id] = RelationDraft(
                relation_id=link.link_id,
                source_kind="event",
                source_id=link.semantic_source_event_id,
                target_kind="event",
                target_id=link.semantic_target_event_id,
                relation_type=link.relation_type or "",
                reason=link.reason,
                source_operation_id=link.source_operation_local_key,
                is_active=link.is_active,
                evidence=bound,
                producer_agent_id=link.producer_agent_id,
            )
    check_rows = snapshot["checks"]
    check_evidence = smap.fetch_evidence(session, "check_id", [row.check_id for row in check_rows])
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
                producer_agent_id=check.producer_agent_id,
            )
        elif check.source_event_id is not None and check.target_event_id is not None:
            key = (
                min(check.source_event_id, check.target_event_id),
                max(check.source_event_id, check.target_event_id),
            )
            draft.structure_reviews[key] = StructureReviewDraft(
                source_event_id=check.source_event_id,
                target_event_id=check.target_event_id,
                disposition=_checked_disposition(check.disposition, ("contains", "part_of", "related", "independent")),
                reason=check.reason,
                snapshot_hash=check.snapshot_hash or "",
                evidence=bound_check,
                producer_agent_id=check.producer_agent_id,
            )
