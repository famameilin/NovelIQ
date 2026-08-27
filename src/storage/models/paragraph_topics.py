"""
段落主题表 ORM 模型定义

paragraph_topics 保存每个段落（LDA 文档）的主题推断结果（设计文档
《章节粒度分析指标重设计》§5.4）：每个有效段落是一个 LDA 文档，
章节/全书主题概率按 inference_token_count 加权聚合，禁止等权求和。
"""

from __future__ import annotations

from sqlalchemy import (
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ParagraphTopic(Base):
    """
    段落主题表

    每行是一个段落对一个主题的推断权重；topic_weight 与
    inference_token_count 用于按 token 加权聚合章节/全书主题。
    """

    __tablename__ = "paragraph_topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False
    )
    paragraph_id: Mapped[int] = mapped_column(Integer, nullable=False)
    topic_id: Mapped[int] = mapped_column(Integer, nullable=False)
    topic_weight: Mapped[float] = mapped_column(Float, nullable=False)
    inference_token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "paragraph_id"],
            ["paragraphs.run_id", "paragraphs.paragraph_id"],
            ondelete="CASCADE",
        ),
        # 防重跑翻倍：同 (run_id, paragraph_id, topic_id) 唯一
        UniqueConstraint("run_id", "paragraph_id", "topic_id", name="uq_paragraph_topics_run_para_topic"),
        Index("idx_paragraph_topics_run_paragraph", "run_id", "paragraph_id"),
        Index("idx_paragraph_topics_topic_id", "topic_id"),
        Index("idx_paragraph_topics_run_id", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<ParagraphTopic(run_id={self.run_id}, paragraph_id={self.paragraph_id}, topic_id={self.topic_id})>"
