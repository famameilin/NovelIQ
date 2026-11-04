"""正式语言产物的完整性校验"""

from __future__ import annotations

from src.storage import Storage


def is_linguistic_complete(session: Storage, run_id: str) -> bool:
    """仅复用覆盖全部段落且逐段统计齐全的正式语言产物"""
    row = session.reads.linguistic.get_completion_counts(run_id)
    if row["completed"] > row["statistics_completed"]:
        raise ValueError("正式语言统计不符合完整性契约")
    return row["total"] > 0 and row["statistics_completed"] == row["total"]
