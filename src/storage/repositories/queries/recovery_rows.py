"final agents annotation agent 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import (
    Agent,
    ChapterAnnotation,
)


def list_recoverable_executions(_session, ordered_chapters, run_id):
    executions = (
        select(Agent.id)
        .join(ChapterAnnotation, ChapterAnnotation.agent_id == Agent.id)
        .where(Agent.run_id == run_id, ChapterAnnotation.chapter_id.in_(ordered_chapters))
    )
    return _session.scalars(executions)
