"agents diagnosis domain 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import DiagnosisReport


def agents_diagnosis_domain_retain_pending_cases_1(_session, value_1):
    return _session.scalar(select(DiagnosisReport.report_id).where(DiagnosisReport.agent_id == value_1))
