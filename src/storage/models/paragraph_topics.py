"""
段落主题表 ORM 模型定义（2026-10-16 全库 3NF 改造）

paragraph_topics 保存每个段落（LDA 文档）的完整 K 维主题推断分布
（《分析能力扩展路线图》§5.10）：每个推断状态为 complete 的段落恰有 K 行，
topic_id 完整覆盖 0..K-1，每段 topic_weight 和在数值容差内等于 1。

完整 K 维覆盖与权重和由数据库延迟约束触发器验证；token 数与推断状态统一
从 paragraph_metrics 读取，模型 K 从分析运行合同读取。
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Float, ForeignKeyConstraint, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ParagraphTopic(Base):
    """
    段落主题表

    每行是一个段落对一个主题的完整分布权重；只有推断状态为 complete 的
    段落可以写入主题行（跨表约束由延迟触发器保证）。
    """

    __tablename__ = "paragraph_topics"
    __table_args__ = (
        CheckConstraint("topic_weight >= 0 AND topic_weight <= 1", name="ck_paragraph_topics_weight_range"),
        ForeignKeyConstraint(
            ["run_id", "paragraph_id"],
            ["paragraphs.run_id", "paragraphs.paragraph_id"],
            ondelete="CASCADE",
        ),
        # 单主题段落序列：主键已覆盖按段落读取
        Index("idx_paragraph_topics_topic_paragraph", "run_id", "topic_id", "paragraph_id"),
        {"comment": "段落主题表：段落×主题的完整 LDA 分布权重（每完成段恰 K 行，和为 1）"},
    )

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="所属分析运行")
    paragraph_id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="所属段落编号")
    topic_id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主题 id（run 内完整覆盖 0..K-1）")
    topic_weight: Mapped[float] = mapped_column(Float, nullable=False, comment="主题权重（段内权重和为 1）")

    def __repr__(self) -> str:
        return (
            f"<ParagraphTopic(run_id={self.run_id}, paragraph_id={self.paragraph_id}, "
            f"topic_id={self.topic_id})>"
        )
