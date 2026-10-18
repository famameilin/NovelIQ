"event trees diagnosis persistence 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import (
    DIAGNOSIS_ROLES,
    Execution,
    GraphFact,
)


def event_trees_diagnosis_persistence_session_executions_1(_session, session_id):
    return _session.scalar(select(Execution.session_run_id).where(Execution.execution_id == session_id))


def event_trees_diagnosis_persistence_session_executions_2(_session, run_id):
    return _session.scalars(
        select(Execution.execution_id).where(Execution.run_id == run_id, Execution.role.in_(DIAGNOSIS_ROLES))
    )


def event_trees_diagnosis_persistence_assert_fact_declarations_bound_1(_session, executions):
    return _session.scalars(
        select(GraphFact.declaration_id).where(
            GraphFact.direct_producer_execution_id.in_(executions), GraphFact.declaration_id.is_not(None)
        )
    )
