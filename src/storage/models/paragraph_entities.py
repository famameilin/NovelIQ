"""
LTP 实体候选表 ORM 模型定义

paragraph_entities 保存 LTP NER 输出的实体候选（《分析能力扩展路线图》§5.4），
不产生人物身份或关系事实；候选与 Agent 图谱结果的对照只在审核 API 中
给出，不自动写入关系图。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
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

from .base import Base, naive_utcnow


class ParagraphEntity(Base):
    """LTP 实体候选表（一个候选一行）"""

    __tablename__ = "paragraph_entities"
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
        {"comment": "LTP 实体候选表：NER 输出的实体候选（一个候选一行），不产生身份或关系事实"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="自增主键")
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, comment="所属分析运行")
    paragraph_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="所属段落编号")
    surface_text: Mapped[str] = mapped_column(Text, nullable=False, comment="候选原文")
    raw_entity_type: Mapped[str] = mapped_column(String(50), nullable=False, comment="LTP 原始实体类型")
    normalized_entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="归一实体类型")
    local_start_char: Mapped[int] = mapped_column(Integer, nullable=False, comment="段内起始字符偏移")
    local_end_char: Mapped[int] = mapped_column(Integer, nullable=False, comment="段内结束字符偏移")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True, comment="置信度")
    source_kind: Mapped[str] = mapped_column(String(30), nullable=False, comment="来源种类")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=naive_utcnow, comment="创建时间"
    )

    def __repr__(self) -> str:
        return f"<ParagraphEntity(run_id={self.run_id}, paragraph_id={self.paragraph_id}, text={self.surface_text!r})>"
