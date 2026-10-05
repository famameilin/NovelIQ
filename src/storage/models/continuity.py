"""章节不可变正式标注 ORM 模型"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow() -> datetime:
    """2026-08-05 用于生成连续性业务表统一的 UTC 时间"""
    return datetime.now(UTC)


class ChapterAnnotationRecord(Base):
    """2026-08-05 用于保存每个 run 章节唯一的完整正式标注"""

    __tablename__ = "chapter_annotations"

    annotation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    chapter_id: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # 2026-10-05 队列删除后 formal_work_id 只是铸造回执的溯源标识，不再是 work_items 外键
    formal_work_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    source_manifest_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "chapter_id", name="uq_chapter_annotations_run_chapter"),
        Index("idx_chapter_annotations_run_chapter", "run_id", "chapter_id"),
    )
