"""
LTP 实体候选表 ORM 模型定义

paragraph_entities 保存 LTP NER 输出的实体候选（《分析能力扩展路线图》§5.4），
不产生人物身份或关系事实；候选与 Agent 图谱结果的对照只在审核 API 中
给出，不自动写入关系图。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    CHAR,
    BigInteger,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow() -> datetime:
    """created_at 默认值：UTC 带时区当前时间（避免模块导入期求值）"""
    return datetime.now(UTC)


class ParagraphEntity(Base):
    """LTP 实体候选表（一个候选一行）"""

    __tablename__ = "paragraph_entities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    paragraph_id: Mapped[int] = mapped_column(Integer, nullable=False)
    surface_text: Mapped[str] = mapped_column(Text, nullable=False)
    raw_entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    normalized_entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    local_start_char: Mapped[int] = mapped_column(Integer, nullable=False)
    local_end_char: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    source_content_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "paragraph_id"],
            ["paragraphs.run_id", "paragraphs.paragraph_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id", "paragraph_id"],
            ["paragraph_linguistic_features.run_id", "paragraph_linguistic_features.paragraph_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "run_id",
            "paragraph_id",
            "local_start_char",
            "local_end_char",
            "raw_entity_type",
            "surface_text",
            name="uq_entities_run_para_span_type_text",
        ),
        Index("idx_entities_run_para_start", "run_id", "paragraph_id", "local_start_char"),
        Index("idx_entities_run_normalized", "run_id", "normalized_entity_type"),
    )

    def __repr__(self) -> str:
        return f"<ParagraphEntity(run_id={self.run_id}, paragraph_id={self.paragraph_id}, text={self.surface_text!r})>"