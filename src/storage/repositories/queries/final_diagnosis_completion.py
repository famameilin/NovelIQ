"final diagnosis completion 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import CompleteEvent
from src.storage.repositories.narrative_records import run_execution_ids


def final_diagnosis_completion_has_diagnosis_data_1(_session, run_id):
    return _session.scalar(
        select(CompleteEvent.event_id)
        .where(CompleteEvent.producer_execution_id.in_(run_execution_ids(run_id)))
        .limit(1)
    )
