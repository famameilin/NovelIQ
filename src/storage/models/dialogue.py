"""对话记录独立表 ORM 模型"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
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
    """2026-08-11 用于生成对话记录统一的 UTC 时间"""
    return datetime.now(UTC)


class DialogueRecord(Base):
    """2026-08-11 用于保存系统绑定对话原文位置与语义结果，案例解决直接更新本表"""

    __tablename__ = "dialogue_records"

    dialogue_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    chapter_id: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_key: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    start: Mapped[int] = mapped_column(Integer, nullable=False)
    end: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tone: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_inner_monologue: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["chapter_id", "run_id"],
            ["chapters.chapter_id", "chapters.run_id"],
            ondelete="CASCADE",
            name="dialogue_records_chapter_run_fkey",
        ),
        Index("idx_dialogue_records_run_chapter", "run_id", "chapter_id"),
        # 2026-08-12 唯一约束兜底 (run_id, candidate_key)：案例解决按该键 scalar_one_or_none 定位，
        # 唯一性此前仅靠应用层保证，防止重复候选键导致定位歧义
        UniqueConstraint(
            "run_id",
            "candidate_key",
            name="uq_dialogue_records_run_candidate",
        ),
    )

    def __repr__(self) -> str:
        return f"<DialogueRecord(dialogue_id={self.dialogue_id}, run_id={self.run_id}, chapter_id={self.chapter_id})>"
