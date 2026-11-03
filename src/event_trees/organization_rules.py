"""事件组织的保存前约束与原文证据校验"""

from __future__ import annotations

from typing import Protocol

from src.event_trees.organization_models import (
    CompleteEventDraft,
    EventOutcomeDraft,
    EventQueueDraft,
    NarrativeOrganization,
    QueueReferenceDraft,
    RelationDraft,
)
from src.event_trees.organization_queries import _global_positions, _paragraph_rows, _run_events
from src.event_trees.queues import QueueGraph
from src.storage import Storage
from src.utils.identity import text_digest


class OrganizationValidationState(Protocol):
    "保存校验所需的事件内容与包含状态"

    events: dict[str, CompleteEventDraft]
    queue_references: dict[tuple[str, str], QueueReferenceDraft]
    relations: dict[str, RelationDraft]

    def queue_graph(self, *, require_complete: bool = False, producers: set[str] | None = None) -> QueueGraph: ...
    def content_digest(self) -> str: ...
    def structure_digest(self) -> str: ...

    queues: dict[str, EventQueueDraft]
    event_line_ids: set[str]
    line_names: dict[str, str]


def validate_organization(
    session: Storage, run_id: str, organization: NarrativeOrganization, draft: OrganizationValidationState
) -> None:
    """保存前校验同 run 端点、独立结果及每项真实证据"""
    organization = NarrativeOrganization.model_validate(organization.model_dump())
    all_ids = set(_run_events(session, run_id))
    all_ids.update(item.event_id for item in organization.events)
    draft.events = {item.event_id: item for item in organization.events}
    draft.queue_references = {
        (item.parent_tree_id, item.child_tree_id): item for item in organization.queue_references
    }
    draft.relations = {item.relation_id: item for item in organization.relations}
    draft.queues = {item.tree_id: item for item in organization.queues}
    draft.event_line_ids = set(organization.event_line_ids)
    draft.line_names = dict(organization.event_line_names)
    producers = {
        item.producer_agent_id
        for records in (organization.events, organization.queues, organization.queue_references)
        for item in records
        if item.producer_agent_id is not None
    }
    draft.queue_graph(require_complete=True, producers=producers)
    if draft.content_digest() != organization.content_snapshot:
        raise ValueError("身份快照与实际来源判断不一致")
    if draft.structure_digest() != organization.structure_snapshot:
        raise ValueError("结构快照与实际接受记录不一致")
    refs = [
        ref
        for records in (
            organization.events,
            organization.relations,
            organization.outcomes,
            organization.queues,
            organization.queue_references,
        )
        for item in records
        for ref in item.evidence
    ]
    for records in (
        organization.events,
        organization.queue_references,
        organization.relations,
        organization.outcomes,
        organization.queues,
    ):
        for record in records:
            if not record.producer_agent_id:
                raise ValueError("诊断贡献缺少真实 Agent 写出者")
    paragraphs = _paragraph_rows(session, run_id, {ref.paragraph_id for ref in refs})
    for ref in refs:
        row = paragraphs.get(ref.paragraph_id)
        if (
            row is None
            or int(row.chapter_id) != ref.chapter_id
            or ref.char_end > len(row.text)
            or text_digest(row.text[ref.char_start : ref.char_end]) != ref.text_hash
        ):
            raise ValueError("组织证据坐标或哈希与本 run 原文不一致")
        if ref.event_id is not None and ref.event_id not in all_ids:
            raise ValueError("组织证据引用的完整事件不属于本 run")
    positioned_records: list[CompleteEventDraft | EventOutcomeDraft] = [*organization.events, *organization.outcomes]
    positions = _global_positions(session, run_id, {ref.paragraph_id for ref in refs})
    for outcome in positioned_records:
        if outcome.first_text_position != min(positions[ref.paragraph_id] + ref.char_start for ref in outcome.evidence):
            raise ValueError("结果正文排序位置必须由证据派生")
