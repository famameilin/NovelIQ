"""将各领域独立查询序列化为既有 pipeline 响应"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from src.case_pool.read import case_state_view
from src.event_trees.read.book_state import connections_view
from src.work.queries import work_progress_view


def book_state_view(session: Session, run_id: str) -> dict[str, Any]:
    progress = work_progress_view(session, run_id)
    cases = case_state_view(session, run_id)
    return {
        "completed_chapters": progress["completed_chapters"],
        "total_chapters": progress["total_chapters"],
        "saved_work_count": progress["saved_work_count"],
        **cases,
        "connections": connections_view(session, run_id),
        "works": progress["works"],
    }
