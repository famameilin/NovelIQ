"从 src/diagnosis/completion.py 分离的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import AnalysisAssessment, DiagnosisReport, Execution


def diagnosis_completion_has_diagnosis_data_1(_session, run_id):
    return _session.scalars(
        select(DiagnosisReport)
        .join(Execution, Execution.execution_id == DiagnosisReport.session_id)
        .where(Execution.session_run_id == run_id)
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
