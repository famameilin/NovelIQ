"""
运行统计相关操作

运行状态、完成度检查等操作

2026-08-14 M8b：ChunkCurve 引用移除——聚合完成度改按 global_stats 判定
（曲线事实源为 paragraph_curves）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from src.agents.diagnosis.schema import CloudAnalysis as CloudAnalysisSchema
from src.storage.models import (
    AnalysisOutput,
    Chapter,
    GlobalStats,
    Paragraph,
    ParagraphLinguisticFeature,
    ParagraphTopic,
    ParagraphTopicInference,
    TopicModelRun,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _payload_has_valid_diagnosis_contract(payload: dict[str, Any]) -> bool:
    """2026-08-20 用于确认诊断产物包含完整焦点合同且能通过当前模型校验"""
    raw_focus_characters = payload.get("focus_characters")
    raw_main_characters = payload.get("main_characters")
    raw_core_cast = payload.get("core_cast")

    # 正式诊断必须有焦点结构和三组角色名单，只有旧字段的半成品行不算完成
    if (
        payload.get("focus_structure") not in {"single", "dual", "ensemble"}
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
            payload.get("foreshadow_expectation") is not None,
            bool(payload.get("arc_scores")),
            bool(payload.get("genre_labels")),
            bool(payload.get("style_labels")),
            bool(payload.get("topic_labels")),
            payload.get("diagnosis") is not None,
            payload.get("value_logic_type") is not None,
            payload.get("value_logic_reason") is not None,
            payload.get("power_stance_score") is not None,
            payload.get("power_stance_reason") is not None,
            payload.get("common_people_dignity") is not None,
            payload.get("dignity_reason") is not None,
            payload.get("cultural_depth_score") is not None,
            payload.get("cultural_depth_reason") is not None,
            payload.get("narrative_arc_type") is not None,
            payload.get("theme_color") is not None,
        )
    ):
        return False

    try:
        CloudAnalysisSchema.model_validate(payload)
    except Exception:
        return False
    return True


def has_topic_data(session: Session, run_id: str) -> bool:
    """主题数据必须具有本轮 topic_model_runs 模型记录"""
    model_count = (
        session.execute(
            select(func.count()).select_from(TopicModelRun).where(TopicModelRun.run_id == run_id)
        ).scalar()
        or 0
    )
    return model_count > 0


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
        select(AnalysisOutput)
        .where(AnalysisOutput.run_id == run_id, AnalysisOutput.kind == "cloud_analysis")
        .order_by(AnalysisOutput.created_at.desc(), AnalysisOutput.output_id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest_row is None:
        return False
    return _payload_has_valid_diagnosis_contract(latest_row.payload)


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
