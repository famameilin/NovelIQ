"""案例状态独立只读视图"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from src.storage.repositories.book_state import case_records


def case_state_view(session: Session, run_id: str) -> dict[str, Any]:
    states = dict.fromkeys(("pending", "resolved", "deferred", "contested"), 0)
    cases = []
    for case in case_records(session, run_id):
        states[case.state] += 1
        cases.append({"case_id": case.case_id, "description": case.description, "state": case.state})
    return {"case_states": states, "cases": cases}
