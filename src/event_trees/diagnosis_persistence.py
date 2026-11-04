"按当前运行已保存的事件与关系恢复诊断草稿"

from __future__ import annotations

from typing import Literal, cast

from src.event_trees import storage_map as smap
from src.event_trees.organization import EventOrganizationDraft
from src.event_trees.organization_models import (
    BoundOrganizationEvidence,
    CompleteEventDraft,
    EventQueueDraft,
    QueueReferenceDraft,
    RelationDraft,
)
from src.event_trees.organization_queries import _evidence_payloads, _run_event_dicts, _run_events
from src.storage import Storage


def hydrate_draft_from_run(session: Storage, run_id: str, draft: EventOrganizationDraft) -> None:
    """把本 run 已保存的行水合进草稿内存：续跑在既有成果上继续

    行是会话保存留下的正式形状行；保存随后按完整内存状态计算快照。
    """
    rows = _run_events(session, run_id)
    trees = {
        row.group_id: row
        for row in session.reads.events.list_execution_trees(smap.run_execution_ids(session, run_id))
    }
    if not rows and not trees:
        return
    dicts = _run_event_dicts(session, run_id)
    snapshot = session.diagnosis.session_rows(run_id)
    event_evidence = smap.fetch_evidence(session, "complete_event_id", list(rows))
    draft.event_line_ids = {tree_id for tree_id, row in trees.items() if row.is_event_line}
    draft.line_names = {
        tree_id: line_name
        for tree_id, row in trees.items()
        if (line_name := getattr(row, "line_name", None)) is not None
    }
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
            payoff_likelihood=cast(Literal["high", "medium", "low"] | None, row.payoff_likelihood),
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
        if link.child_tree_id is not None and link.parent_tree_id is not None:
            draft.queue_references[(link.parent_tree_id, link.child_tree_id)] = QueueReferenceDraft(
                parent_tree_id=link.parent_tree_id,
                child_tree_id=link.child_tree_id,
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

    members: dict[str, list] = {}
    for link in session.reads.events.list_queue_links(run_id):
        if link.tree_id is not None:
            members.setdefault(link.tree_id, []).append(link)
    for tree_id, tree in trees.items():
        items = members.get(tree_id, [])
        items.sort(key=lambda item: item.position)
        refs = smap.fetch_evidence(session, "narrative_link_id", [items[0].link_id]) if items else {}
        bound = (
            [
                BoundOrganizationEvidence(**row)
                for row in _evidence_payloads(session, run_id, refs.get(items[0].link_id, []))
            ]
            if items
            else []
        )
        draft.queues[tree_id] = EventQueueDraft(
            tree_id=tree_id,
            tree_key=tree.tree_key,
            title=tree.title,
            description=tree.description,
            event_ids=[item.member_event_id for item in items],
            producer_agent_id=tree.producer_agent_id,
            reason=items[0].reason if items else "",
            evidence=bound,
        )
