"agents diagnosis persistence 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import Agent, DiagnosisReport, GraphEntity


def agents_diagnosis_persistence_character_entity_ids_1(_session, run_id):
    return _session.scalars(
        select(GraphEntity).where(GraphEntity.run_id == run_id, GraphEntity.entity_type == "character")
    )


def agents_diagnosis_persistence_save_diagnosis_report_1(_session, agent_id):
    return _session.get(Agent, agent_id)


def agents_diagnosis_persistence_existing_report_1(_session, run_id):
    return _session.scalars(
        select(DiagnosisReport).join(Agent, Agent.id == DiagnosisReport.agent_id).where(Agent.run_id == run_id)
    )
