"""章节标注案例池与案例解决映射 ORM 模型"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "chapter_id", name="uq_chapter_annotations_run_chapter"),
        Index("idx_chapter_annotations_run_chapter", "run_id", "chapter_id"),
    )


class CasePoolCase(Base):
    """2026-08-07 用于保存带稳定目标的活动或已解决案例"""

    __tablename__ = "case_pool_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    case_type: Mapped[str] = mapped_column("type", String(50), nullable=False)
    chunk_id: Mapped[int] = mapped_column(Integer, nullable=False)
    keys: Mapped[list] = mapped_column(JSONB, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    target_key: Mapped[str] = mapped_column(String(64), nullable=False)
    target_ref: Mapped[dict] = mapped_column(JSONB, nullable=False)
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_by_annotation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chapter_annotations.annotation_id", ondelete="CASCADE"),
        nullable=False,
    )
    last_surfaced_annotation_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("chapter_annotations.annotation_id", ondelete="SET NULL"),
        nullable=True,
    )
    last_surfaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
            name="case_pool_cases_chunk_run_fkey",
        ),
        CheckConstraint(
            "state IN ('active', 'resolved')",
            name="ck_case_pool_cases_state",
        ),
        UniqueConstraint("run_id", "target_key", name="uq_case_pool_cases_run_target_key"),
        Index("idx_case_pool_cases_run_state", "run_id", "state"),
        Index("idx_case_pool_cases_run_type", "run_id", "type"),
        Index("idx_case_pool_cases_rotation", "run_id", "state", "last_surfaced_at", "id"),
    )


class CaseResolutionMapping(Base):
    """2026-08-07 用于关联 pulled 案例解决结果与历史事实修订"""

    __tablename__ = "case_resolution_mappings"

    mapping_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    annotation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chapter_annotations.annotation_id", ondelete="CASCADE"),
        nullable=False,
    )
    case_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("case_pool_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    case_type: Mapped[str] = mapped_column("type", String(50), nullable=False)
    target_ref: Mapped[dict] = mapped_column(JSONB, nullable=False)
    resolution: Mapped[dict] = mapped_column(JSONB, nullable=False)
    evidence_chunk_id: Mapped[int] = mapped_column(Integer, nullable=False)
    target_fact_id: Mapped[str] = mapped_column(String(128), nullable=False)
    target_fact_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["evidence_chunk_id", "run_id"],
            ["chunks.chunk_id", "chunks.run_id"],
            ondelete="CASCADE",
            name="case_resolution_mappings_evidence_chunk_run_fkey",
        ),
        UniqueConstraint("run_id", "case_id", name="uq_case_resolution_mappings_run_case"),
        Index("idx_case_resolution_mappings_annotation", "run_id", "annotation_id"),
        Index("idx_case_resolution_mappings_case", "run_id", "case_id"),
    )
