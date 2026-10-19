"diagnosis completion 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import Agent, AnalysisAssessment, DiagnosisReport


def diagnosis_completion_has_diagnosis_data_1(_session, run_id):
    return _session.scalars(
        select(DiagnosisReport)
        .join(Agent, Agent.id == DiagnosisReport.agent_id)
        .where(Agent.run_id == run_id)
        .order_by(DiagnosisReport.created_at.desc(), DiagnosisReport.report_id.desc())
        .limit(1)
    ).first()


def diagnosis_completion_has_cast_1(_session, cast_role, report):
    return _session.scalar(
        select(AnalysisAssessment.assessment_id)
        .where(AnalysisAssessment.report_id == report.report_id, AnalysisAssessment.cast_role == cast_role)
        .limit(1)
    )


def diagnosis_completion_has_label_1(_session, column, report):
    if column not in {"genre_label", "topic_label", "style_label"}:
        raise ValueError("无效的固定查询种类")
    column = getattr(AnalysisAssessment, column)
    return _session.scalar(
        select(AnalysisAssessment.assessment_id)
        .where(AnalysisAssessment.report_id == report.report_id, column.is_not(None))
        .limit(1)
    )
