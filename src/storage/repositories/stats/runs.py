"""
运行统计相关操作

运行状态、完成度检查等操作

2026-08-14 M8b：ChunkCurve 引用移除——聚合完成度改按 global_stats 判定
（曲线事实源为 paragraph_curves）。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from src.models.cloud.schema import CloudAnalysis as CloudAnalysisSchema
from src.storage.models import (
    Chapter,
    CloudAnalysis,
    GlobalStats,
    Paragraph,
    ParagraphLinguisticFeature,
    ParagraphTopic,
    ParagraphTopicInference,
    TopicModelRun,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _parse_json_text_field(value: str | None) -> object | None:
    """2026-08-20 用于解析诊断表中的 JSON 文本字段并将非法值视为缺失"""
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _row_has_valid_diagnosis_contract(row: CloudAnalysis) -> bool:
    """2026-08-20 用于确认诊断行包含完整焦点合同且能通过当前模型校验"""
    raw_focus_characters = _parse_json_text_field(row.focus_characters)
    raw_main_characters = _parse_json_text_field(row.main_characters)
    raw_core_cast = _parse_json_text_field(row.core_cast)
    raw_arc_scores = _parse_json_text_field(row.arc_scores)
    raw_genre_labels = _parse_json_text_field(row.genre_labels)
    raw_style_labels = _parse_json_text_field(row.style_labels)
    raw_topic_labels = _parse_json_text_field(row.topic_labels)

    # 正式诊断必须有焦点结构和三组角色名单，只有旧字段的半成品行不算完成
    if (
        row.focus_structure not in {"single", "dual", "ensemble"}
        or not isinstance(raw_focus_characters, list)
        or not raw_focus_characters
        or not isinstance(raw_main_characters, list)
        or not raw_main_characters
        or not isinstance(raw_core_cast, list)
        or not raw_core_cast
    ):
        return False

    if not any(
        (
            row.foreshadow_expectation is not None,
            bool(raw_arc_scores),
            bool(raw_genre_labels),
            bool(raw_style_labels),
            bool(raw_topic_labels),
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
            row.theme_color is not None,
        )
    ):
        return False

    try:
        CloudAnalysisSchema.model_validate(
            {
                "novel_id": row.novel_id,
                "foreshadow_expectation": row.foreshadow_expectation,
                "arc_scores": raw_arc_scores if isinstance(raw_arc_scores, dict) else {},
                "genre_labels": raw_genre_labels if isinstance(raw_genre_labels, list) else [],
                "style_labels": raw_style_labels if isinstance(raw_style_labels, list) else [],
                "topic_labels": raw_topic_labels if isinstance(raw_topic_labels, (dict, list)) else {},
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
                "focus_characters": raw_focus_characters,
                "main_characters": raw_main_characters,
                "core_cast": raw_core_cast,
                "theme_color": row.theme_color,
            }
        )
    except Exception:
        return False
    return True


def has_topic_data(session: Session, run_id: str) -> bool:
    """检查指定运行是否有主题数据。

    新契约（§5.8）以 topic_model_runs 契约行存在判定主题阶段完成；
    旧 Top-5 运行无契约行时回退查 paragraph_topics 行数，避免迁移期误判。
    """
    model_count = (
        session.execute(
            select(func.count()).select_from(TopicModelRun).where(TopicModelRun.run_id == run_id)
        ).scalar()
        or 0
    )
    if model_count > 0:
        return True
    topic_count = (
        session.execute(
            select(func.count()).select_from(ParagraphTopic).where(ParagraphTopic.run_id == run_id)
        ).scalar()
        or 0
    )
    return topic_count > 0


def has_linguistic_data(session: Session, run_id: str) -> bool:
    """检查指定运行是否有语言结构基础数据（paragraph_linguistic_features 行）"""
    count = (
        session.execute(
            select(func.count())
            .select_from(ParagraphLinguisticFeature)
            .where(ParagraphLinguisticFeature.run_id == run_id)
        ).scalar()
        or 0
    )
    return count > 0


def is_linguistic_complete(session: Session, run_id: str) -> bool:
    """恢复任务只复用覆盖全部段落的语言特征，不能把首批数据当作阶段完成"""
    row = session.execute(
        select(
            func.count(Paragraph.paragraph_id).label("total"),
            func.count(ParagraphLinguisticFeature.paragraph_id).label("completed"),
        ).select_from(Paragraph).outerjoin(
            ParagraphLinguisticFeature,
            (ParagraphLinguisticFeature.run_id == Paragraph.run_id)
            & (ParagraphLinguisticFeature.paragraph_id == Paragraph.paragraph_id),
        ).where(Paragraph.run_id == run_id)
    ).mappings().one()
    return row["total"] > 0 and row["completed"] == row["total"]


def is_topic_model_complete(session: Session, run_id: str) -> bool:
    """模型契约、每段终态与完整 K 维分布齐备后，才能在恢复时跳过主题阶段"""
    model = session.get(TopicModelRun, run_id)
    if model is None:
        return False
    topic_counts = select(
        ParagraphTopic.paragraph_id, func.count().label("topic_count"),
    ).where(ParagraphTopic.run_id == run_id).group_by(ParagraphTopic.paragraph_id).subquery()
    row = session.execute(
        select(
            func.count(Paragraph.paragraph_id).label("total"),
            func.count(ParagraphTopicInference.paragraph_id).filter(
                ParagraphTopicInference.inference_status.in_(("complete", "empty_after_preprocess", "empty_bow")),
            ).label("settled"),
            func.count(ParagraphTopicInference.paragraph_id).filter(
                ParagraphTopicInference.inference_status == "complete",
            ).label("complete"),
            func.count(ParagraphTopicInference.paragraph_id).filter(
                ParagraphTopicInference.inference_status == "complete", topic_counts.c.topic_count == model.num_topics,
            ).label("full_distributions"),
        ).select_from(Paragraph).outerjoin(
            ParagraphTopicInference,
            (ParagraphTopicInference.run_id == Paragraph.run_id)
            & (ParagraphTopicInference.paragraph_id == Paragraph.paragraph_id),
        ).outerjoin(topic_counts, topic_counts.c.paragraph_id == Paragraph.paragraph_id)
        .where(Paragraph.run_id == run_id)
    ).mappings().one()
    return (
        row["total"] > 0 and row["settled"] == row["total"]
        and row["complete"] == row["full_distributions"] == model.inference_paragraph_count
    )


def has_diagnosis_data(session: Session, run_id: str) -> bool:
    """检查指定运行是否有诊断数据。Args: session/run_id；Returns: 是否存在。"""
    latest_row = session.execute(
        select(CloudAnalysis).where(CloudAnalysis.run_id == run_id).order_by(CloudAnalysis.id.desc()).limit(1)
    ).scalar_one_or_none()
    if latest_row is None:
        return False
    return _row_has_valid_diagnosis_contract(latest_row)


def is_aggregate_complete(session: Session, run_id: str) -> bool:
    """检查聚合阶段是否完成（chapters+global_stats 均存在）。Args: session/run_id；Returns: 是否完成。"""
    chapters_count = (
        session.execute(select(func.count()).select_from(Chapter).where(Chapter.run_id == run_id)).scalar() or 0
    )

    # 2026-08-14 M8b：聚合阶段唯一落库产物是 global_stats（chunk_curves 已下线），
    # 完成判定改以 global_stats 存在为准
    stats_count = (
        session.execute(select(func.count()).select_from(GlobalStats).where(GlobalStats.run_id == run_id)).scalar() or 0
    )

    return chapters_count > 0 and stats_count > 0
