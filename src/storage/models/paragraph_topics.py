"段落主题表 ORM 模型定义（2026-10-16 全库 3NF 改造）"

from __future__ import annotations

from sqlalchemy import CheckConstraint, Float, ForeignKeyConstraint, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.storage.ids import new_id
from src.storage.uuid_type import Uuid7 as Uuid

from .base import Base


class ParagraphTopic(Base):
    "段落主题表"

    __tablename__ = "paragraph_topics"
    __table_args__ = (
        UniqueConstraint("run_id", "paragraph_id", "topic_id", name="uq_paragraph_topics_business_key"),
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

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=new_id, autoincrement=False, comment="UUIDv7 独立主键"
    )
    run_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), comment="所属分析运行", nullable=False)
    paragraph_id: Mapped[int] = mapped_column(Integer, comment="所属段落编号", nullable=False)
    topic_id: Mapped[int] = mapped_column(Integer, comment="主题 id（run 内完整覆盖 0..K-1）", nullable=False)
    topic_weight: Mapped[float] = mapped_column(Float, nullable=False, comment="主题权重（段内权重和为 1）")

    def __repr__(self) -> str:
        return f"<ParagraphTopic(run_id={self.run_id}, paragraph_id={self.paragraph_id}, topic_id={self.topic_id})>"
