"""
段落主题表 ORM 模型定义

paragraph_topics 保存每个段落（LDA 文档）的完整 K 维主题推断分布
（《分析能力扩展路线图》§5.10）：每个完成段落恰有 K 行，topic_id 完整覆盖
0..K-1，每段 topic_weight 和在数值容差内等于 1。

token 数与推断状态统一从 paragraph_topic_inference 读取，不在 K 条主题行
重复保存；章节/全书聚合按 inference_token_count 加权，禁止等权求和。
"""

from __future__ import annotations

from sqlalchemy import Float, ForeignKeyConstraint, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ParagraphTopic(Base):
    """
    段落主题表

    每行是一个段落对一个主题的完整分布权重；只有推断状态为 complete 的
    段落可以写入主题行，主键 (run_id, paragraph_id, topic_id) 保证主题 ID
    无缺口且不重复。
    """

    __tablename__ = "paragraph_topics"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    paragraph_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic_weight: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(["run_id"], ["topic_model_runs.run_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["run_id", "paragraph_id"],
            ["paragraph_topic_inference.run_id", "paragraph_topic_inference.paragraph_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id", "paragraph_id"],
            ["paragraphs.run_id", "paragraphs.paragraph_id"],
            ondelete="CASCADE",
        ),
        # 单主题段落序列：主键已覆盖按段落读取
        Index("idx_paragraph_topics_topic_paragraph", "run_id", "topic_id", "paragraph_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<ParagraphTopic(run_id={self.run_id}, paragraph_id={self.paragraph_id}, "
            f"topic_id={self.topic_id})>"
        )