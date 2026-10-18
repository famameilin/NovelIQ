"final agents annotation agent 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import (
    Execution,
)


def final_agents_annotation_agent_recover_1(_session, ordered_chapters, value_1):
    executions = select(Execution.execution_id).where(
        Execution.run_id == value_1, Execution.chapter_id.in_(ordered_chapters)
    )
    return _session.scalars(executions)
