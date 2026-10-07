"""
运行统计相关操作

运行状态、完成度检查等操作

2026-08-14 M8b：ChunkCurve 引用移除——聚合完成度改按 global_stats 判定
（曲线事实源为 paragraph_curves）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from src.storage.models import (
    ParagraphLinguisticFeature,
    TopicModelRun,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def has_topic_data(session: Session, run_id: str) -> bool:
    """主题数据必须具有本轮 topic_model_runs 模型记录"""
    model_count = (
        session.execute(select(func.count()).select_from(TopicModelRun).where(TopicModelRun.run_id == run_id)).scalar()
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
