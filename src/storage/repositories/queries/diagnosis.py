"""diagnosis 的固定 SQL 记录查询"""

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import (
    Agent,
    AnalysisAssessment,
    DiagnosisReport,
    GraphEntity,
)


def list_run_reports(_session, run_id):
    return _session.scalars(
        select(DiagnosisReport).join(Agent, Agent.id == DiagnosisReport.agent_id).where(Agent.run_id == run_id)
    )


def find_latest_report(_session, run_id):
    return _session.scalars(
        select(DiagnosisReport)
        .join(Agent, Agent.id == DiagnosisReport.agent_id)
        .where(Agent.run_id == run_id)
        .order_by(DiagnosisReport.created_at.desc(), DiagnosisReport.report_id.desc())
        .limit(1)
    ).first()


def find_cast_assessment(_session, cast_role, report):
    return _session.scalar(
        select(AnalysisAssessment.assessment_id)
        .where(AnalysisAssessment.report_id == report.report_id, AnalysisAssessment.cast_role == cast_role)
        .limit(1)
    )


def find_labeled_assessment(_session, column, report):
    if column not in {"genre_label", "topic_label", "style_label"}:
        raise ValueError("无效的固定查询种类")
    column = getattr(AnalysisAssessment, column)
    return _session.scalar(
        select(AnalysisAssessment.assessment_id)
        .where(AnalysisAssessment.report_id == report.report_id, column.is_not(None))
        .limit(1)
    )


def get_latest_report(_session, run_id):
    return _session.scalars(
        select(DiagnosisReport)
        .join(Agent, Agent.id == DiagnosisReport.agent_id)
        .where(Agent.run_id == run_id)
        .order_by(DiagnosisReport.created_at.desc(), DiagnosisReport.report_id.desc())
        .limit(1)
    ).first()


def list_topic_assessments(_session, report_id):
    return _session.scalars(
        select(AnalysisAssessment)
        .where(AnalysisAssessment.report_id == report_id, AnalysisAssessment.topic_label.is_not(None))
        .order_by(AnalysisAssessment.topic_id)
    )


def list_character_scores(_session, report_id):
    return _session.execute(
        select(GraphEntity.canonical_name, AnalysisAssessment.character_score)
        .join(AnalysisAssessment, AnalysisAssessment.scored_entity_id == GraphEntity.entity_id)
        .where(AnalysisAssessment.report_id == report_id, AnalysisAssessment.character_score.is_not(None))
    )


def list_labels(_session, column, report_id):
    if column not in {"genre_label", "topic_label", "style_label"}:
        raise ValueError("无效的固定查询种类")
    column = getattr(AnalysisAssessment, column)
    return _session.scalars(
        select(column)
        .where(AnalysisAssessment.report_id == report_id, column.is_not(None))
        .order_by(AnalysisAssessment.ordinal)
    )


def list_cast_names(_session, cast_role, report_id):
    stmt = (
        select(GraphEntity.canonical_name)
        .join(AnalysisAssessment, AnalysisAssessment.cast_entity_id == GraphEntity.entity_id)
        .where(AnalysisAssessment.report_id == report_id, AnalysisAssessment.cast_role == cast_role)
        .order_by(AnalysisAssessment.ordinal)
    )
    return _session.scalars(stmt)


def find_latest_run_report(_session, run_id):
    return _session.scalars(
        select(DiagnosisReport)
        .join(Agent, Agent.id == DiagnosisReport.agent_id)
        .where(Agent.run_id == run_id)
        .order_by(DiagnosisReport.created_at.desc(), DiagnosisReport.report_id.desc())
        .limit(1)
    ).first()
