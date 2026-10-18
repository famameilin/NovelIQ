"从 src/agents/diagnosis/domain.py 分离的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import DiagnosisReport


def agents_diagnosis_domain_retain_pending_cases_1(_session, value_1):
    return _session.scalar(select(DiagnosisReport.report_id).where(DiagnosisReport.session_id == value_1))
