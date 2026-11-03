"event trees organization 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import (
    Agent,
    DiagnosisReport,
    NarrativeGroup,
)
from src.storage.repositories import narrative_records as smap


def list_published_group_ids(_session, run_id):
    stmt = select(NarrativeGroup.group_id).where(
        NarrativeGroup.producer_agent_id.in_(smap.run_execution_ids(run_id)),
        NarrativeGroup.kind == "outcome",
    )
    return _session.scalars(stmt)






def get_report(_session, report_id):
    return _session.get(DiagnosisReport, report_id)


def get_report_owner(_session, report):
    return _session.get(Agent, report.agent_id)














