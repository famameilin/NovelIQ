"""已保存工作产生的有效事件连接视图"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from src.storage.repositories.book_state import connection_records, event_records, work_records


def connections_view(session: Session, run_id: str) -> list[dict[str, Any]]:
    producers = {item.work_id: item.invocation_id for item in work_records(session, run_id)}
    nodes = {
        node.event_id: node
        for node in event_records(session, run_id)
        if node.author_work_id is not None and producers.get(node.author_work_id) == node.producer_invocation_id
    }
    node_ids = set(nodes)
    return [
        {
            "connection_id": edge.edge_id,
            "parent_node_id": edge.source_event_id,
            "node_id": edge.target_event_id,
            "type": edge.cause_role or edge.edge_type,
            "author_work_id": edge.author_work_id,
            "parent_description": nodes[edge.source_event_id].description,
            "description": nodes[edge.target_event_id].description,
            "parent_chapter_id": edge.source_chapter_id,
            "chapter_id": edge.target_chapter_id,
        }
        for edge in connection_records(session, run_id)
        if edge.is_active
        and edge.author_work_id in producers
        and {edge.source_event_id, edge.target_event_id} <= node_ids
    ]
