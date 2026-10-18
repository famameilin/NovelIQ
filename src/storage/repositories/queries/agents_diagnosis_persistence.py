"从 src/agents/diagnosis/persistence.py 分离的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import DiagnosisReport, Execution, GraphEntity


def agents_diagnosis_persistence_character_entity_ids_1(_session, run_id):
    return _session.scalars(
        select(GraphEntity).where(GraphEntity.run_id == run_id, GraphEntity.entity_type == "character")
    )


def agents_diagnosis_persistence_save_diagnosis_report_1(_session, session_id):
    return _session.get(Execution, session_id)


def agents_diagnosis_persistence_published_report_1(_session, run_id):
    return _session.scalars(
        select(DiagnosisReport)
        .join(Execution, Execution.execution_id == DiagnosisReport.session_id)
        .where(Execution.session_run_id == run_id)
    )
