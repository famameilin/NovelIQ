"""
固定短语命中表 ORM 模型定义

paragraph_phrase_hits 同时保存正式词表命中和四字候选（《分析能力扩展路线图》
§5.5）；只有经过词表确认（active 状态）且被匹配规则选中的行进入正式密度。
候选行不伪造词表来源，同起点或交叠命中全部保留用于审计。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    CHAR,
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

from .base import Base


def _utcnow() -> datetime:
    """created_at 默认值：UTC 带时区当前时间（避免模块导入期求值）"""
    return datetime.now(UTC)


class ParagraphPhraseHit(Base):
    """固定短语命中表（一个命中一行）"""

    __tablename__ = "paragraph_phrase_hits"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    paragraph_id: Mapped[int] = mapped_column(Integer, nullable=False)
    surface_text: Mapped[str] = mapped_column(Text, nullable=False)
    phrase_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    local_start_char: Mapped[int] = mapped_column(Integer, nullable=False)
    local_end_char: Mapped[int] = mapped_column(Integer, nullable=False)
    match_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    lexicon_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lexicon_version_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_metric_hit: Mapped[bool] = mapped_column(Boolean, nullable=False)
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
            "match_kind",
            "surface_text",
            name="uq_phrase_hits_run_para_span_kind_text",
        ),
        Index("idx_phrase_hits_run_para_start", "run_id", "paragraph_id", "local_start_char"),
        Index("idx_phrase_hits_run_kind_metric", "run_id", "match_kind", "is_metric_hit"),
    )

    def __repr__(self) -> str:
        return (
            f"<ParagraphPhraseHit(run_id={self.run_id}, paragraph_id={self.paragraph_id}, "
            f"text={self.surface_text!r})>"
        )