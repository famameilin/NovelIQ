"""对话记录独立表 ORM 模型"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text
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
    chunk_id: Mapped[int] = mapped_column(Integer, nullable=False)
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
            ["chunk_id", "run_id"],
            ["chunks.chunk_id", "chunks.run_id"],
            ondelete="CASCADE",
            name="dialogue_records_chunk_run_fkey",
        ),
        Index("idx_dialogue_records_run_chunk", "run_id", "chunk_id"),
        Index("idx_dialogue_records_run_candidate", "run_id", "candidate_key"),
    )

    def __repr__(self) -> str:
        return f"<DialogueRecord(dialogue_id={self.dialogue_id}, run_id={self.run_id}, chunk_id={self.chunk_id})>"
