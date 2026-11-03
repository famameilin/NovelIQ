"""runs 的固定 SQL 记录查询"""

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import Run


def get_run(_session, run_id):
    return _session.get(Run, run_id)

def get_novel_id(_session, run_id):
    return _session.scalar(select(Run.novelid).where(Run.id == run_id))

def find_novel_id(_session, run_id):
    return _session.execute(select(Run.novelid).where(Run.id == run_id)).scalar_one_or_none()
