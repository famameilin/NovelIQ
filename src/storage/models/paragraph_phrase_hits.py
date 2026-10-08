"""
固定短语命中表 ORM 模型定义

paragraph_phrase_hits 同时保存正式词表命中和四字候选（《分析能力扩展路线图》
§5.5）；只有经过词表确认（active 状态）且被匹配规则选中的行进入正式密度。
候选行不伪造词表来源，同起点或交叠命中全部保留用于审计。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, naive_utcnow


class ParagraphPhraseHit(Base):
    """固定短语命中表（一个命中一行）"""

    __tablename__ = "paragraph_phrase_hits"
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
            "match_kind",
            "surface_text",
            name="uq_phrase_hits_run_para_span_kind_text",
        ),
        Index("idx_phrase_hits_run_para_start", "run_id", "paragraph_id", "local_start_char"),
        Index("idx_phrase_hits_run_kind_metric", "run_id", "match_kind", "is_metric_hit"),
        {"comment": "固定短语命中表：词表命中与四字候选（一个命中一行），交叠命中全保留供审计"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="自增主键")
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, comment="所属分析运行")
    paragraph_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="所属段落编号")
    surface_text: Mapped[str] = mapped_column(Text, nullable=False, comment="命中原文")
    phrase_type: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="短语类型")
    local_start_char: Mapped[int] = mapped_column(Integer, nullable=False, comment="段内起始字符偏移")
    local_end_char: Mapped[int] = mapped_column(Integer, nullable=False, comment="段内结束字符偏移")
    match_kind: Mapped[str] = mapped_column(String(30), nullable=False, comment="匹配方式")
    lexicon_key: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="词表条目键（非词表来源为 NULL）",
    )
    is_metric_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, comment="是否计入正式指标密度")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=naive_utcnow, comment="创建时间"
    )

    def __repr__(self) -> str:
        return (
            f"<ParagraphPhraseHit(run_id={self.run_id}, paragraph_id={self.paragraph_id}, "
            f"text={self.surface_text!r})>"
        )
