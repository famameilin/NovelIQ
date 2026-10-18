"""运行级统计存在性查询

- 主题模型：本轮实际构建记录读 analysis_runs 的 lda_* 列（实际主题数 K 是
  唯一正式落点），不靠请求侧 requested_num_topics。
- 语言结构基础数据：完成事实读 paragraph_metrics.linguistic_completed_at
  （零词元段落同样有完成行）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from src.storage.models import AnalysisRun, ParagraphMetric

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def has_topic_data(session: Session, run_id: str) -> bool:
    """是否存在本轮 LDA 实际构建记录（analysis_runs.lda_num_topics 非空）"""
    return (
        session.scalar(
            select(AnalysisRun.lda_num_topics).where(
                AnalysisRun.run_id == run_id,
                AnalysisRun.lda_num_topics.is_not(None),
            )
        )
        is not None
    )


def has_linguistic_data(session: Session, run_id: str) -> bool:
    """是否存在语言结构基础数据（任一段落带语言完成事实）"""
    return (
        session.scalar(
            select(ParagraphMetric.paragraph_id)
            .where(
                ParagraphMetric.run_id == run_id,
                ParagraphMetric.linguistic_completed_at.is_not(None),
            )
            .limit(1)
        )
        is not None
    )
