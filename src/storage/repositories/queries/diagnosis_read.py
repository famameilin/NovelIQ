"diagnosis read 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import AnalysisAssessment, AnalysisRun, DiagnosisReport, Execution, GraphEntity


def diagnosis_read_fetch_diagnosis_payload_1(_session, run_id):
    return _session.scalar(select(AnalysisRun.novel_id).where(AnalysisRun.run_id == run_id))


def diagnosis_read_fetch_diagnosis_payload_2(_session, run_id):
    return _session.scalars(
        select(DiagnosisReport)
        .join(Execution, Execution.execution_id == DiagnosisReport.session_id)
        .where(Execution.session_run_id == run_id)
        .order_by(DiagnosisReport.created_at.desc(), DiagnosisReport.report_id.desc())
        .limit(1)
    ).first()


def diagnosis_read_fetch_diagnosis_payload_3(_session, report_id):
    return _session.scalars(
        select(AnalysisAssessment)
        .where(AnalysisAssessment.report_id == report_id, AnalysisAssessment.topic_label.is_not(None))
        .order_by(AnalysisAssessment.topic_id)
    )


def diagnosis_read_fetch_diagnosis_payload_4(_session, report_id):
    return _session.execute(
        select(GraphEntity.canonical_name, AnalysisAssessment.character_score)
        .join(AnalysisAssessment, AnalysisAssessment.scored_entity_id == GraphEntity.entity_id)
        .where(AnalysisAssessment.report_id == report_id, AnalysisAssessment.character_score.is_not(None))
    )


def diagnosis_read_labels_1(_session, column, report_id):
    if column not in {"genre_label", "topic_label", "style_label"}:
        raise ValueError("无效的固定查询种类")
    column = getattr(AnalysisAssessment, column)
    return _session.scalars(
        select(column)
        .where(AnalysisAssessment.report_id == report_id, column.is_not(None))
        .order_by(AnalysisAssessment.ordinal)
    )


def diagnosis_read_members_1(_session, cast_role, report_id):
    stmt = (
        select(GraphEntity.canonical_name)
        .join(AnalysisAssessment, AnalysisAssessment.cast_entity_id == GraphEntity.entity_id)
        .where(AnalysisAssessment.report_id == report_id, AnalysisAssessment.cast_role == cast_role)
        .order_by(AnalysisAssessment.ordinal)
    )
    return _session.scalars(stmt)
