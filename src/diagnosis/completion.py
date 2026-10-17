"""所属领域的产物完整性查询，供恢复编排调用

2026-10-16 全库 3NF 改造（35 表冻结结构）：从 diagnosis_reports 报告头、
analysis_assessments 的标签/名单条目与 complete_events 发布事实判定，
正文与评分列、组织发布事实分别核对，不再读取通用产物 payload。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.event_trees.storage_map import run_execution_ids


def has_diagnosis_data(session: Session, run_id: str) -> bool:
    """检查指定运行是否有完整诊断数据。Args: session/run_id；Returns: 是否存在。"""
    from src.storage.models import (
        AnalysisAssessment,
        CompleteEvent,
        DiagnosisReport,
        Execution,
    )

    report = session.scalars(
        select(DiagnosisReport)
        .join(Execution, Execution.execution_id == DiagnosisReport.session_id)
        .where(Execution.session_run_id == run_id)
        .order_by(DiagnosisReport.created_at.desc(), DiagnosisReport.report_id.desc())
        .limit(1)
    ).first()
    if report is None:
        return False
    # 正式组织必须已发布：本 run 存在完整事件（生产者执行属于本 run），且报告冻结了身份与结构快照
    published = session.scalar(
        select(CompleteEvent.event_id)
        .where(CompleteEvent.producer_execution_id.in_(run_execution_ids(run_id)))
        .limit(1)
    )
    if published is None or report.identity_snapshot is None or report.structure_snapshot is None:
        return False

    def _has_cast(cast_role: str) -> bool:
        return (
            session.scalar(
                select(AnalysisAssessment.assessment_id)
                .where(
                    AnalysisAssessment.report_id == report.report_id,
                    AnalysisAssessment.cast_role == cast_role,
                )
                .limit(1)
            )
            is not None
        )

    def _has_label(column) -> bool:
        return (
            session.scalar(
                select(AnalysisAssessment.assessment_id)
                .where(AnalysisAssessment.report_id == report.report_id, column.is_not(None))
                .limit(1)
            )
            is not None
        )

    # 正式诊断必须有焦点结构和三组角色名单，只有旧字段的半成品行不算完成
    if report.focus_structure not in {"single", "dual", "ensemble"}:
        return False
    if not (_has_cast("focus") and _has_cast("main") and _has_cast("core")):
        return False

    return any(
        (
            report.diagnosis is not None,
            report.value_logic_type is not None,
            report.value_logic_reason is not None,
            report.power_stance_score is not None,
            report.power_stance_reason is not None,
            report.common_people_dignity is not None,
            report.dignity_reason is not None,
            report.cultural_depth_score is not None,
            report.cultural_depth_reason is not None,
            report.narrative_arc_type is not None,
            report.theme_color is not None,
            _has_label(AnalysisAssessment.genre_label),
            _has_label(AnalysisAssessment.style_label),
            _has_label(AnalysisAssessment.topic_label),
        )
    )
