"""
运行统计相关操作

创建时间: 2026-03-17
创建者: TraeAI
任务: code-quality-refactor - 拆分stats_repository
说明: 运行状态、完成度检查等操作

修改时间: 2026-03-30
修改者: CodeBuddy
任务: db-schema-cleanup
修改内容: 合并 EmotionCurve + RhythmCurve 引用为 ChunkCurve
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from src.models.cloud.schema import CloudAnalysis as CloudAnalysisSchema
from src.storage.models import Chunk, ChunkCurve, ChunkTopic, CloudAnalysis

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _parse_json_text_field(value: str | None) -> object | None:
    """
    创建时间: 2026-04-27
    创建者: Codex
    任务: protagonist-focus-contract-review-fixes-round2
    说明: diagnosis 完成态现在必须校验新焦点合同；
    这里在 storage 层做最小 JSON 解析，避免只按“表里有行”误判完成。
    """
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _row_has_valid_diagnosis_contract(row: CloudAnalysis) -> bool:
    """
    创建时间: 2026-04-27
    创建者: Codex
    任务: protagonist-focus-contract-review-fixes-round2
    说明: 旧 row、半成品 row 或迁移前残留 row 不应再把 diagnosis 阶段标成已完成；
    只有能通过新 CloudAnalysis 合同校验的行，才算真正的 diagnosis 结果。
    """
    raw_focus_characters = _parse_json_text_field(row.focus_characters)
    raw_main_characters = _parse_json_text_field(row.main_characters)
    raw_core_cast = _parse_json_text_field(row.core_cast)
    raw_arc_scores = _parse_json_text_field(row.arc_scores)
    raw_topic_labels = _parse_json_text_field(row.topic_labels)

    has_any_diagnosis_signal = any(
        (
            row.foreshadow_expectation is not None,
            bool(raw_arc_scores),
            row.narrative_type is not None,
            bool(_parse_json_text_field(row.topic_labels)),
            row.diagnosis is not None,
            row.value_logic_type is not None,
            row.value_logic_reason is not None,
            row.power_stance_score is not None,
            row.power_stance_reason is not None,
            row.common_people_dignity is not None,
            row.dignity_reason is not None,
            row.cultural_depth_score is not None,
            row.cultural_depth_reason is not None,
            row.narrative_arc_type is not None,
            row.focus_structure is not None,
            bool(raw_focus_characters),
            bool(raw_main_characters),
            bool(raw_core_cast),
            row.theme_color is not None,
        )
    )
    if not has_any_diagnosis_signal:
        return False

    try:
        CloudAnalysisSchema.model_validate(
            {
                "novel_id": row.novel_id,
                "foreshadow_expectation": row.foreshadow_expectation,
                "arc_scores": raw_arc_scores if isinstance(raw_arc_scores, dict) else {},
                "narrative_type": row.narrative_type,
                "topic_labels": raw_topic_labels if isinstance(raw_topic_labels, list) else [],
                "diagnosis": row.diagnosis,
                "value_logic_type": row.value_logic_type,
                "value_logic_reason": row.value_logic_reason,
                "power_stance_score": row.power_stance_score,
                "power_stance_reason": row.power_stance_reason,
                "common_people_dignity": row.common_people_dignity,
                "dignity_reason": row.dignity_reason,
                "cultural_depth_score": row.cultural_depth_score,
                "cultural_depth_reason": row.cultural_depth_reason,
                "narrative_arc_type": row.narrative_arc_type,
                "focus_structure": row.focus_structure,
                "focus_characters": raw_focus_characters if isinstance(raw_focus_characters, list) else [],
                "main_characters": raw_main_characters if isinstance(raw_main_characters, list) else [],
                "core_cast": raw_core_cast if isinstance(raw_core_cast, list) else [],
                "theme_color": row.theme_color,
            }
        )
    except Exception:
        return False

    return True


def has_aggregated_data(session: Session, run_id: str) -> bool:
    """
    检查指定运行是否有聚合数据

    Args:
        session: 数据库会话
        run_id: 运行ID

    Returns:
        是否有聚合数据
    """
    curve_count = (
        session.execute(select(func.count()).select_from(ChunkCurve).where(ChunkCurve.run_id == run_id)).scalar() or 0
    )

    return curve_count > 0


def has_topic_data(session: Session, run_id: str) -> bool:
    """
    检查指定运行是否有主题数据

    Args:
        session: 数据库会话
        run_id: 运行ID

    Returns:
        是否有主题数据
    """
    count = (
        session.execute(select(func.count()).select_from(ChunkTopic).where(ChunkTopic.run_id == run_id)).scalar() or 0
    )
    return count > 0


def has_diagnosis_data(session: Session, run_id: str) -> bool:
    """
    检查指定运行是否有诊断数据

    Args:
        session: 数据库会话
        run_id: 运行ID

    Returns:
        是否有诊断数据
    """
    rows = session.execute(
        select(CloudAnalysis).where(CloudAnalysis.run_id == run_id).order_by(CloudAnalysis.id.desc())
    ).scalars()
    return any(_row_has_valid_diagnosis_contract(row) for row in rows)


def is_aggregate_complete(session: Session, run_id: str) -> bool:
    """
    检查聚合阶段是否完成

    Args:
        session: 数据库会话
        run_id: 运行ID

    Returns:
        聚合是否完成
    """
    chunks_count = session.execute(select(func.count()).select_from(Chunk).where(Chunk.run_id == run_id)).scalar() or 0

    curve_count = (
        session.execute(select(func.count()).select_from(ChunkCurve).where(ChunkCurve.run_id == run_id)).scalar() or 0
    )

    return chunks_count > 0 and curve_count >= chunks_count
