"""
段落主题推断状态表 ORM 模型定义

paragraph_topic_inference 每个段落一行保存：原始 token 数、实际进入 LDA BOW
的 token 数、推断状态与不可用原因（《分析能力扩展路线图》§5.9）。

token 数与分布守恒审计只在本表保存一次，供 paragraph_topics 的 K 条主题行
按段落聚合时使用，避免按主题行重复放大分母。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKeyConstraint, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, naive_utcnow


class ParagraphTopicInference(Base):
    """
    段落主题推断状态表

    inference_status 取值：complete / empty_after_preprocess / empty_bow / failed。
    complete 状态必须有 inference_token_count > 0、无不可用原因，且
    distribution_sum 在容差内等于 1；非完成状态必须有不可用原因，
    且不得存在对应的 paragraph_topics 行。
    """

    __tablename__ = "paragraph_topic_inference"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "paragraph_id"],
            ["paragraphs.run_id", "paragraphs.paragraph_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["run_id"], ["topic_model_runs.run_id"], ondelete="CASCADE"),
        Index("idx_topic_inference_status_paragraph", "run_id", "inference_status", "paragraph_id"),
        {"comment": "段落主题推断状态表：token 数、推断状态与不可用原因（每段一行，聚合分母唯源）"},
    )

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="所属分析运行")
    paragraph_id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="所属段落编号")
    source_token_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="原始 token 数")
    inference_token_count: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="进入 LDA BOW 的 token 数（聚合分母）",
    )
    inference_status: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="推断状态（complete/empty_after_preprocess/empty_bow/failed）"
    )
    unavailable_reason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="不可用原因（非完成状态必有）")
    distribution_sum: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        comment="分布权重和（complete 时约为 1）",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=naive_utcnow, comment="创建时间"
    )

    def __repr__(self) -> str:
        return (
            f"<ParagraphTopicInference(run_id={self.run_id}, paragraph_id={self.paragraph_id}, "
            f"status={self.inference_status})>"
        )
