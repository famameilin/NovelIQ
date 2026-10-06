"""结果 API 的成功 work、有效连接与纯文字案例查询"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents.annotation.work import completed_chapters
from src.storage.models import AnnotationWork, BookCase, Chapter, EventEdge, EventNode


def book_state_view(session: Session, run_id: str) -> dict[str, Any]:
    work = session.execute(select(AnnotationWork).where(AnnotationWork.run_id == run_id)).scalars().all()
    total = session.query(Chapter).filter(Chapter.run_id == run_id).count()
    states = dict.fromkeys(("pending", "resolved", "deferred", "contested"), 0)
    cases = []
    for case in session.execute(select(BookCase).where(BookCase.run_id == run_id)).scalars():
        states[case.state] += 1
        cases.append({"case_id": case.case_id, "description": case.description, "state": case.state})
    producers = {item.work_id: item.invocation_id for item in work}
    nodes = {
        node.event_id: node for node in session.execute(select(EventNode).where(EventNode.run_id == run_id)).scalars()
        if node.author_work_id is not None and producers.get(node.author_work_id) == node.producer_invocation_id
    }
    node_ids = set(nodes)
    connections = [
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
        for edge in session.execute(select(EventEdge).where(EventEdge.run_id == run_id)).scalars()
        if edge.is_active and edge.author_work_id in producers
        and {edge.source_event_id, edge.target_event_id} <= node_ids
    ]
    return {
        "completed_chapters": len(completed_chapters(work)),
        "total_chapters": total,
        "saved_work_count": len(work),
        "case_states": states,
        "cases": cases,
        "connections": connections,
        "works": [
            {
                "work_id": item.work_id,
                "chapter_id": item.chapter_id,
                "role": item.role,
                "state": item.state,
                "invocation_id": item.invocation_id,
            }
            for item in work
        ],
    }
