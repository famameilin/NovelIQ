"event trees diagnosis persistence 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import (
    DIAGNOSIS_ROLES,
    Agent,
    GraphFact,
)


def event_trees_diagnosis_persistence_session_executions_1(_session, agent_id):
    return _session.scalar(select(Agent.run_id).where(Agent.id == agent_id))


def event_trees_diagnosis_persistence_session_executions_2(_session, run_id):
    return _session.scalars(select(Agent.id).where(Agent.run_id == run_id, Agent.type.in_(DIAGNOSIS_ROLES)))


def event_trees_diagnosis_persistence_assert_fact_annotation_events_bound_1(_session, executions):
    return _session.scalars(
        select(GraphFact.event_id).where(
            GraphFact.direct_producer_agent_id.in_(executions), GraphFact.event_id.is_not(None)
        )
    )
