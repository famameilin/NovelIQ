"""事件草稿对外部事件身份的引用汇总"""

from __future__ import annotations

from typing import Any


def referenced_event_ids(draft: Any, producers: set[str]) -> set[str]:
    """本生产者的关系、证据与成员引用到的事件身份"""
    referenced: set[str] = set()
    for relation in draft.relations.values():
        if relation.producer_agent_id in producers:
            referenced.update((relation.source_id, relation.target_id))
    for queue in draft.queues.values():
        if queue.producer_agent_id in producers:
            referenced.update(queue.event_ids)
    records = [
        *[item for item in draft.events.values() if item.producer_agent_id in producers],
        *[item for item in draft.queues.values() if item.producer_agent_id in producers],
        *[item for item in draft.queue_references.values() if item.producer_agent_id in producers],
        *[item for item in draft.relations.values() if item.producer_agent_id in producers],
    ]
    for item in records:
        referenced.update(ref.event_id for ref in item.evidence if ref.event_id is not None)
    return referenced
